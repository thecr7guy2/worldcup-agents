"""Intelligence agent — the single source of shared FACTS.

One model (with web search) builds the knowledge every competitor reads
identically. The data flow (DESIGN §3) is:

    build_dossier(team)        living, layered, REUSABLE per team
        -> build_pre_match_report(fixture, team)   dossier + fresh news, frozen at cutoff
    build_match_context(fixture)                   neutral H2H / venue / stakes
        -> assemble_briefing(fixture)              DETERMINISTIC assembly, NO LLM, NO odds

The load-bearing rules (breaking any silently corrupts the competition):

* **Neutral.** Facts only — never a lean, a pick, or a win probability.
* **No odds.** Odds are facts but are withheld until the bet step.
* **Temporal integrity.** A report's `cutoff_at` is recorded and must precede
  kickoff; the model is told to use only what was known by then.
* **Layered dossier.** baseline / rolling_form / latest_match keep recency
  proportionate by LAYOUT, not by a "please don't overreact" instruction.
* **Cheap assembly.** The briefing concatenates frozen reports; shared facts are
  never regenerated, so no re-summarization can drop a fact or inject a lean.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from . import db
from .config import (
    INTEL_MAX_TOKENS,
    INTEL_WEB_MAX_RESULTS,
    INTELLIGENCE_MODEL,
    ModelSpec,
)
from .llm import LLMError, complete
from .models import (
    Fixture,
    LateUpdate,
    MatchBriefing,
    PostMatchReport,
    PreMatchReport,
    Team,
    TeamDossier,
)

# Shared system prompt for every intelligence call. This is where neutrality and
# the no-odds rule are enforced — downstream prediction quality depends on it.
SYSTEM = """You are a football intelligence analyst compiling FACTUAL briefings on \
FIFA World Cup 2026 teams. Your output is read identically by several prediction \
models; your job is to inform them, never to influence which way they lean.

STRICT RULES:
1. FACTS ONLY — never opinions, predictions, or leans. Allowed: "ranked 3rd by \
FIFA", "unbeaten in 8", "star striker doubtful (hamstring)". Forbidden: "they \
should win", "the likely outcome", "I expect", or any win probability.
2. NEVER mention betting odds, market prices, bookmakers, or implied probability. \
Odds are deliberately withheld from this stage.
3. Prefer concrete dated specifics: results with scores and dates, named players, \
injury/suspension status, manager, formation.
4. Do NOT fabricate. If you cannot verify a fact, omit it — never invent scores, \
injuries, or call-ups.
5. Be concise and neutral in tone.
6. Web search results are ALREADY provided to you. Do NOT narrate searching ("I'll \
search…", "Let me look…", "I have sufficient information…"). Output ONLY the report \
content itself — no preamble, no meta-commentary, no sign-off."""

_DOSSIER_HEADERS = ("BASELINE", "ROLLING FORM", "LATEST MATCH")


def _split_sections(text: str, headers: tuple[str, ...]) -> dict[str, str]:
    """Split model output into sections keyed by header.

    Tolerates `#`/`##`/`###` prefixes and trailing colons. A header that the
    model omitted maps to an empty string (callers decide if that's fatal).
    """
    # Match a header either by its markdown hashes (anywhere — models sometimes
    # glue a preamble onto the first one, e.g. "...team.### BASELINE") or as a
    # standalone line. The end-of-line lookahead stops the header words from
    # matching inside prose ("the baseline quality of the squad").
    alt = "|".join(re.escape(h) for h in headers)
    pattern = re.compile(
        r"(?:#{1,4}[ \t]*|(?m:^)[ \t]*)\*{0,2}("
        + alt
        + r")\*{0,2}[ \t]*:?[ \t]*(?=\r?\n|$)",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    out = {h: "" for h in headers}
    for i, m in enumerate(matches):
        key = next(h for h in headers if h.lower() == m.group(1).lower())
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[key] = text[start:end].strip()
    return out


# First-person *process* narration the model sometimes prepends despite the
# system rule ("I'll research…", "Let me verify…"). Anchored to the very start
# and limited to process verbs, so it never matches the opening of a real
# factual report (which is neutral third-person).
_NARRATION_START = re.compile(
    r"^(?:I'?ll|I will|Let me|I have|I'?ve|Now I|Based on (?:my|the) search|Let's)\b",
    re.IGNORECASE,
)
# A markdown heading, tolerant of the model gluing it onto the narration with no
# preceding newline ("…head-to-head.# MATCH CONTEXT"). Requires "# " + content.
_HEADING = re.compile(r"#{1,6}[ \t]+\S")


def _strip_preamble(text: str) -> str:
    """Drop a leading search-narration block if the text begins with one.

    Only fires when the text *starts* with first-person process narration, then
    cuts to the first markdown heading (or, failing that, the first paragraph
    break). A normal report starts with neutral facts and is left untouched.
    """
    t = text.strip()
    if not _NARRATION_START.match(t):
        return t
    m = _HEADING.search(t)
    if m and m.start() > 0:
        return t[m.start() :].strip()
    para = t.find("\n\n")
    if para > 0:
        return t[para:].strip()
    return t


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- Dossier (reusable, per team) ----------------------------------------


def build_dossier(
    conn: sqlite3.Connection,
    team: Team,
    *,
    model: ModelSpec = INTELLIGENCE_MODEL,
    force: bool = False,
) -> TeamDossier:
    """Build (or reuse) a team's living, layered dossier via web search."""
    if not force:
        existing = db.get_dossier(conn, team.id)
        if existing:
            return existing

    prompt = f"""Compile a factual dossier on the {team.name} men's national football \
team ahead of FIFA World Cup 2026. Search the web for current information.

Write EXACTLY these three sections, with these headers, in this order:

### BASELINE
Slow-moving identity: current FIFA ranking, squad quality and key players, playing \
identity/typical formation, manager, pedigree at World Cups. (~120 words)

### ROLLING FORM
The last 5-6 competitive matches (qualifiers/friendlies) with opponents, scores, and \
dates; the trend in results, goals for/against. (~120 words)

### LATEST MATCH
Only the single most recent match: opponent, score, date, and one line on how it went. \
Keep this short — it is one data point, not the whole picture. (~60 words)

Facts only. No odds. No prediction about the World Cup."""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="dossier",
        system=SYSTEM,
        max_tokens=INTEL_MAX_TOKENS,  # generous: reasoning must not starve the answer
        temperature=0.3,
        web_search=True,
        web_max_results=INTEL_WEB_MAX_RESULTS,
    )
    db.log_model_call(conn, call)

    secs = _split_sections(text, _DOSSIER_HEADERS)
    missing = [h for h in _DOSSIER_HEADERS if not secs[h]]
    if missing:
        raise LLMError(
            f"dossier for {team.name}: missing/empty sections {missing}. "
            f"Raw output starts: {text[:200]!r}"
        )

    dossier = TeamDossier(
        team_id=team.id,
        updated_at=_now(),
        baseline=secs["BASELINE"],
        rolling_form=secs["ROLLING FORM"],
        latest_match=secs["LATEST MATCH"],
    )
    db.upsert_dossier(conn, dossier)
    return dossier


# ---- Pre-match report (per fixture+team, frozen at cutoff) ----------------


def build_pre_match_report(
    conn: sqlite3.Connection,
    fixture: Fixture,
    team: Team,
    opponent: Team,
    *,
    cutoff: datetime,
    model: ModelSpec = INTELLIGENCE_MODEL,
    force: bool = False,
) -> PreMatchReport:
    """Build (or reuse) a frozen pre-match report for one team in one fixture.

    Layers fresh, cutoff-bounded news on top of the team's dossier. NO odds.
    The opponent is named so the tactical/matchup section is grounded in who they face;
    the report stays per-(team, fixture), so this does not pollute the team's dossier.
    """
    if not force:
        existing = db.get_pre_match_report(conn, fixture.id, team.id)
        if existing:
            return existing

    dossier = build_dossier(conn, team, model=model, force=force)
    today = cutoff.date().isoformat()

    prompt = f"""You are preparing a pre-match report on {team.name} ahead of their FIFA \
World Cup 2026 fixture against {opponent.name}, kicking off {fixture.kickoff.isoformat()}.

TEMPORAL RULE: today is {today}. Use ONLY information publicly known as of today. \
Say NOTHING about the match itself (it has not been played).

Here is the team's standing dossier (background — do not just repeat it; update and \
add to it with the latest news):

[BASELINE] {dossier.baseline}
[ROLLING FORM] {dossier.rolling_form}
[LATEST MATCH] {dossier.latest_match}

Write a neutral, factual report. Format it as markdown using EXACTLY these section \
headers, bold, in this order, each followed by `-` bullet points:

**Availability** — injuries, suspensions, yellow-card risk, probable XI, rotation. \
This is the highest-value signal; put it first. Prefer claims confirmed by an official \
source or corroborated across multiple reports; explicitly mark anything unconfirmed or \
rumored as such rather than stating it as fact.
**Form & trend** — recent results with scores/dates, the trend.
**Stakes & motivation** — must-win vs already-qualified, rest-vs-rotate.
**Tactics & matchup** — formation, style, manager, and how {team.name} matches up \
stylistically against {opponent.name} specifically.
**Rest & conditions** — rest days, travel, fixture congestion, and 2026 conditions \
(US heat, Mexico City altitude, weather).
**Psychology & crowd** — temperament, pressure, host/diaspora crowd factors.

Rules for the format: use these exact bold headers and nothing else — do NOT invent \
other headers, do NOT use ALL-CAPS headers, do NOT add a title or repeat the fixture \
date/venue. If you have no verified facts for a section, omit that whole header rather \
than padding it. Keep the report UNDER ~400 words; prefer short bullets.

Facts only. No odds. No prediction of the result."""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="pre_match",
        fixture_id=fixture.id,
        system=SYSTEM,
        max_tokens=INTEL_MAX_TOKENS,  # generous: reasoning must not starve the answer
        temperature=0.3,
        web_search=True,
        web_max_results=INTEL_WEB_MAX_RESULTS,
    )
    db.log_model_call(conn, call)

    content = _strip_preamble(text)
    if not content:
        raise LLMError(f"pre-match report for {team.name} came back empty")

    report = PreMatchReport(
        fixture_id=fixture.id,
        team_id=team.id,
        cutoff_at=cutoff,
        content=content,
    )
    db.upsert_pre_match_report(conn, report)
    return report


# ---- Match context (per fixture, neutral) --------------------------------


def build_match_context(
    conn: sqlite3.Connection,
    fixture: Fixture,
    home: Team,
    away: Team,
    *,
    cutoff: datetime,
    model: ModelSpec = INTELLIGENCE_MODEL,
) -> str:
    """Neutral per-fixture context: H2H, venue conditions, what's at stake. NO odds."""
    today = cutoff.date().isoformat()
    venue = fixture.venue or "the listed venue"
    prompt = f"""Provide neutral factual MATCH CONTEXT for the FIFA World Cup 2026 \
fixture {home.name} vs {away.name}, kicking off {fixture.kickoff.isoformat()} at \
{venue}.

TEMPORAL RULE: today is {today}; use only information known as of today, and do not \
predict the result.

Format it as markdown using EXACTLY these section headers, bold, in this order, each \
followed by `-` bullet points:

**Head-to-head** — recent meetings between the two sides with scores and dates.
**Venue & conditions** — altitude, expected heat/weather for the kickoff time, pitch/roof.
**What's at stake** — group/bracket situation for each side, even-handed toward both.

Use these exact bold headers and nothing else — no other headers, no ALL-CAPS, no \
title, no repeating the kickoff time. Omit a header entirely if you have no verified \
facts for it. Keep it UNDER ~300 words.

Facts only. No odds. No prediction."""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="match_context",
        fixture_id=fixture.id,
        system=SYSTEM,
        max_tokens=INTEL_MAX_TOKENS,  # generous: reasoning must not starve the answer
        temperature=0.3,
        web_search=True,
        web_max_results=INTEL_WEB_MAX_RESULTS,
    )
    db.log_model_call(conn, call)
    content = _strip_preamble(text)
    if not content:
        raise LLMError(f"match context for fixture {fixture.id} came back empty")
    return content


# ---- Briefing (deterministic assembly — no LLM, no odds) -----------------


def assemble_briefing(
    conn: sqlite3.Connection,
    fixture: Fixture,
    *,
    model: ModelSpec = INTELLIGENCE_MODEL,
    force: bool = False,
) -> MatchBriefing:
    """Assemble the per-fixture briefing every predictor reads. Idempotent/lazy.

    Builds the two pre-match reports + match context as needed, then concatenates
    them deterministically. No LLM call here — shared facts are never regenerated.
    """
    if fixture.home_id is None or fixture.away_id is None:
        raise ValueError(
            f"fixture {fixture.id} has unresolved sides "
            f"({fixture.home_label} vs {fixture.away_label}); "
            "cannot brief until the bracket is resolved"
        )
    if not force:
        existing = db.get_match_briefing(conn, fixture.id)
        if existing:
            return existing

    cutoff = _now()
    if fixture.kickoff <= cutoff:
        raise ValueError(
            f"fixture {fixture.id} kicked off at {fixture.kickoff.isoformat()} "
            f"(<= now {cutoff.isoformat()}); a pre-match briefing would violate "
            "temporal integrity"
        )

    home = db.get_team(conn, fixture.home_id)
    away = db.get_team(conn, fixture.away_id)
    if home is None or away is None:
        raise ValueError(f"fixture {fixture.id}: missing team rows")

    report_home = build_pre_match_report(
        conn, fixture, home, away, cutoff=cutoff, model=model, force=force
    )
    report_away = build_pre_match_report(
        conn, fixture, away, home, cutoff=cutoff, model=model, force=force
    )
    context = build_match_context(conn, fixture, home, away, cutoff=cutoff, model=model)

    group = f", Group {fixture.group}" if fixture.group else ""
    venue = f" · {fixture.venue}" if fixture.venue else ""
    content = (
        f"# MATCH BRIEFING — {home.name} vs {away.name}\n"
        f"{fixture.stage.value}{group}{venue} · "
        f"kickoff {fixture.kickoff.isoformat()}\n\n"
        f"## {home.name} — pre-match report\n{report_home.content}\n\n"
        f"## {away.name} — pre-match report\n{report_away.content}\n\n"
        f"## Match context\n{context}\n\n"
        "---\n"
        "Facts only. Betting odds are withheld here and provided separately at the "
        "betting stage."
    )

    briefing = MatchBriefing(fixture_id=fixture.id, created_at=cutoff, content=content)
    db.upsert_match_briefing(conn, briefing)
    return briefing


def brief_fixture(
    conn: sqlite3.Connection,
    fixture_id: int,
    *,
    model: ModelSpec = INTELLIGENCE_MODEL,
    force: bool = False,
) -> MatchBriefing:
    """Top-level entry: produce and persist the briefing for one fixture."""
    fixture = db.get_fixture(conn, fixture_id)
    if fixture is None:
        raise ValueError(f"no fixture with id {fixture_id}")
    return assemble_briefing(conn, fixture, model=model, force=force)


# ---- Late update (per fixture, fetched just before predictions lock) ------


def build_late_update(
    conn: sqlite3.Connection,
    fixture: Fixture,
    *,
    cutoff: datetime,
    model: ModelSpec = INTELLIGENCE_MODEL,
    force: bool = False,
    max_age_minutes: float | None = None,
) -> LateUpdate:
    """Fetch a short late delta for a fixture: confirmed XI, late injuries/suspensions,
    and matchday weather — the things that move between the T-24h briefing and kickoff.

    Appended to the briefing at predict time (the briefing artifact stays immutable).
    Temporal integrity: `cutoff` must be before kickoff; NO odds, NO prediction.

    Idempotent by default. With `max_age_minutes`, a cached update OLDER than that is
    refreshed instead of reused — so the first (~T-75) fetch can be replaced by a fresher
    one near the lock (~T-50), picking up lineups that have since been confirmed.
    """
    if not force:
        existing = db.get_late_update(conn, fixture.id)
        if existing is not None:
            age_ok = (
                max_age_minutes is None
                or (cutoff - existing.cutoff_at) <= timedelta(minutes=max_age_minutes)
            )
            if age_ok:
                return existing

    if fixture.kickoff <= cutoff:
        raise ValueError(
            f"fixture {fixture.id} kicked off at {fixture.kickoff.isoformat()} "
            f"(<= cutoff {cutoff.isoformat()}); a late update would violate temporal integrity"
        )

    home = db.get_team(conn, fixture.home_id)
    away = db.get_team(conn, fixture.away_id)
    if home is None or away is None:
        raise ValueError(f"fixture {fixture.id}: missing team rows")

    when = cutoff.isoformat()
    prompt = f"""Find the LATEST team news for the FIFA World Cup 2026 fixture {home.name} \
vs {away.name}, kicking off {fixture.kickoff.isoformat()}.

TEMPORAL RULE: right now it is {when}. Use ONLY information published before now, and say \
NOTHING about the match result (it has not been played). This is a short delta on top of an \
earlier report — include only what is fresh and match-relevant near kickoff.

Format as markdown using EXACTLY these bold headers, in this order, each followed by `-` \
bullets; OMIT a header entirely if you have no verified facts for it:

**Confirmed/expected lineups** — starting XI or late line-up news for either side, noting \
how firm it is (official vs expected).
**Late injuries & suspensions** — any fresh availability change since the buildup.
**Matchday conditions** — kickoff-time weather (heat/rain/wind), pitch, late venue notes.

Keep it UNDER ~150 words. Facts only. No odds. No prediction."""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="late_update",
        fixture_id=fixture.id,
        system=SYSTEM,
        max_tokens=INTEL_MAX_TOKENS,  # generous: reasoning must not starve the answer
        temperature=0.3,
        web_search=True,
        web_max_results=INTEL_WEB_MAX_RESULTS,
    )
    db.log_model_call(conn, call)

    content = _strip_preamble(text)
    if not content:
        raise LLMError(f"late update for fixture {fixture.id} came back empty")

    update = LateUpdate(fixture_id=fixture.id, cutoff_at=cutoff, content=content)
    db.upsert_late_update(conn, update)
    return update


# ---- Post-match (read a finished match ONCE -> recap -> update the dossier) ----


def build_post_match_report(
    conn: sqlite3.Connection,
    team: Team,
    *,
    match_label: str,
    played_on: str,
    fixture_id: int | None = None,
    model: ModelSpec = INTELLIGENCE_MODEL,
    force: bool = False,
) -> str:
    """Write a neutral per-team recap of a finished match (DESIGN §3).

    `match_label` describes the completed match (e.g. "friendly vs Serbia,
    won 5-1"); `played_on` is its date. The recap is what feeds the dossier
    update. When `fixture_id` is given (a real World Cup match), the recap is
    persisted to `post_match_report`; for a one-off friendly it is just returned.
    Post-match info legitimately post-dates the match — temporal integrity only
    forbids leaking it into that SAME match's pre-match briefing.
    """
    if fixture_id is not None and not force:
        existing = db.get_post_match_report(conn, fixture_id, team.id)
        if existing:
            return existing.content

    prompt = f"""Write a neutral, factual POST-MATCH recap of {team.name}'s match: \
{match_label}, played {played_on}. Search the web for what happened.

Format it as markdown using EXACTLY these bold section headers, in this order, each \
followed by `-` bullet points:

**What happened** — the result and scoreline, and how the match unfolded.
**Standout performers** — players who stood out (goals, assists, errors), neutrally.
**Fitness & momentum** — any injuries/knocks picked up, and what the result signals \
for the team's form going forward.

Use these exact headers and nothing else; omit a header only if you have no verified \
facts for it. Keep it UNDER ~250 words. Facts only. No odds. No prediction."""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="post_match",
        fixture_id=fixture_id,
        system=SYSTEM,
        max_tokens=INTEL_MAX_TOKENS,  # generous: reasoning must not starve the answer
        temperature=0.3,
        web_search=True,
        web_max_results=INTEL_WEB_MAX_RESULTS,
    )
    db.log_model_call(conn, call)
    content = _strip_preamble(text)
    if not content:
        raise LLMError(f"post-match report for {team.name} came back empty")

    if fixture_id is not None:
        db.upsert_post_match_report(
            conn,
            PostMatchReport(
                fixture_id=fixture_id,
                team_id=team.id,
                created_at=_now(),
                content=content,
            ),
        )
    return content


def build_match_recap(
    conn: sqlite3.Connection,
    fixture: Fixture,
    *,
    model: ModelSpec = INTELLIGENCE_MODEL,
    force: bool = False,
) -> dict[int, str]:
    """Recap a finished fixture in ONE web search, producing a per-team recap for BOTH
    sides at once (dedupes the old one-search-per-team pattern). Persists each as a
    PostMatchReport and returns ``{team_id: recap}``. Post-match info legitimately
    post-dates the match — temporal integrity only forbids leaking it into that same
    match's pre-match briefing.
    """
    home = db.get_team(conn, fixture.home_id)
    away = db.get_team(conn, fixture.away_id)
    if home is None or away is None:
        raise ValueError(f"fixture {fixture.id}: both sides must be resolved to recap")

    if not force:
        h = db.get_post_match_report(conn, fixture.id, home.id)
        a = db.get_post_match_report(conn, fixture.id, away.id)
        if h and a:
            return {home.id: h.content, away.id: a.content}

    hg, ag = fixture.home_goals_90, fixture.away_goals_90
    extra = (
        " (won on penalties)"
        if fixture.went_penalties
        else " (after extra time)" if fixture.went_extra_time else ""
    )
    played_on = fixture.kickoff.date().isoformat()
    score = f"{home.name} {hg}-{ag} {away.name} at 90 minutes{extra}"

    prompt = f"""Write a neutral, factual POST-MATCH recap of this FIFA World Cup 2026 \
match, played {played_on}: {score} ({fixture.stage.value}). Search the web for what \
happened, then cover BOTH teams.

Output EXACTLY this structure, including the two marker lines verbatim:

[[HOME]] {home.name}
**What happened** — the result and scoreline, and how the match unfolded for {home.name}.
**Standout performers** — {home.name} players who stood out (goals, assists, errors), neutrally.
**Fitness & momentum** — injuries/knocks for {home.name}, and what the result signals for their form.

[[AWAY]] {away.name}
**What happened** — the same match from {away.name}'s perspective.
**Standout performers** — {away.name} players who stood out, neutrally.
**Fitness & momentum** — injuries/knocks for {away.name}, and what the result signals for their form.

Use these exact headers; omit a header only if you have no verified facts for it. Keep \
EACH team's block UNDER ~200 words. Facts only. No odds. No prediction."""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="post_match",
        fixture_id=fixture.id,
        system=SYSTEM,
        max_tokens=INTEL_MAX_TOKENS,  # two team blocks; reasoning must not starve them
        temperature=0.3,
        web_search=True,
        web_max_results=INTEL_WEB_MAX_RESULTS,
    )
    db.log_model_call(conn, call)
    content = _strip_preamble(text)
    if not content:
        raise LLMError(f"match recap for fixture {fixture.id} came back empty")

    # Split into per-team recaps on the markers. Fail CLOSED if they're missing or a block
    # is empty: better to raise and let the next tick retry than to store the combined
    # both-teams blob into BOTH dossiers and pollute them.
    if "[[HOME]]" not in content or "[[AWAY]]" not in content:
        raise LLMError(
            f"match recap for fixture {fixture.id} missing [[HOME]]/[[AWAY]] markers"
        )
    before, after = content.split("[[AWAY]]", 1)
    home_recap = before.split("[[HOME]]", 1)[-1].strip()
    away_recap = after.strip()
    if not home_recap or not away_recap:
        raise LLMError(f"match recap for fixture {fixture.id} had an empty team block")

    now = _now()
    for team, recap in ((home, home_recap), (away, away_recap)):
        db.upsert_post_match_report(
            conn,
            PostMatchReport(
                fixture_id=fixture.id,
                team_id=team.id,
                created_at=now,
                content=recap,
            ),
        )
    return {home.id: home_recap, away.id: away_recap}


def update_dossier_after_match(
    conn: sqlite3.Connection,
    team: Team,
    recap: str,
    *,
    model: ModelSpec = INTELLIGENCE_MODEL,
) -> TeamDossier:
    """Fold a post-match recap into the team's living dossier.

    Refreshes the fast-moving layers (`rolling_form`, `latest_match`) while
    leaving the slow `baseline` untouched — recency stays proportionate by
    layout, exactly as the dossier is designed to.
    """
    dossier = db.get_dossier(conn, team.id)
    if dossier is None:
        raise ValueError(
            f"{team.name} has no dossier yet — build one before updating it"
        )

    prompt = f"""Update {team.name}'s living dossier with the latest match just played.

Current ROLLING FORM (last 5-6 matches, the trend):
{dossier.rolling_form}

Current LATEST MATCH:
{dossier.latest_match}

Just-played match recap (the newest data point):
{recap}

Rewrite the two fast-moving layers to incorporate this newest match. Output EXACTLY \
these two sections, with these headers, in this order:

### ROLLING FORM
The last 5-6 matches including this newest one, with the trend; drop the now-oldest \
match if needed to keep it to ~5-6. (~120 words)

### LATEST MATCH
Only this newest match: opponent, score, date, one line on how it went. (~60 words)

Facts only. No odds. No prediction. Do not restate the team's baseline identity."""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="dossier_update",
        system=SYSTEM,
        max_tokens=INTEL_MAX_TOKENS,  # generous: reasoning must not starve the answer
        temperature=0.3,
    )
    db.log_model_call(conn, call)

    secs = _split_sections(text, ("ROLLING FORM", "LATEST MATCH"))
    missing = [h for h in ("ROLLING FORM", "LATEST MATCH") if not secs[h]]
    if missing:
        raise LLMError(
            f"dossier update for {team.name}: missing sections {missing}. "
            f"Raw output starts: {text[:200]!r}"
        )

    updated = TeamDossier(
        team_id=team.id,
        updated_at=_now(),
        baseline=dossier.baseline,  # slow layer unchanged
        rolling_form=secs["ROLLING FORM"],
        latest_match=secs["LATEST MATCH"],
    )
    db.upsert_dossier(conn, updated)
    return updated


# ---- CLI -----------------------------------------------------------------


def _cmd_brief(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    briefing = brief_fixture(conn, args.fixture_id, force=args.force)
    print(briefing.content)


def _cmd_dossier(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    team = db.get_team(conn, args.team_id)
    if team is None:
        raise SystemExit(f"no team with id {args.team_id}")
    d = build_dossier(conn, team, force=args.force)
    print(f"# Dossier — {team.name} (updated {d.updated_at.isoformat()})\n")
    print(f"## Baseline\n{d.baseline}\n")
    print(f"## Rolling form\n{d.rolling_form}\n")
    print(f"## Latest match\n{d.latest_match}")


def _cmd_postmatch(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    team = db.get_team(conn, args.team_id)
    if team is None:
        raise SystemExit(f"no team with id {args.team_id}")

    recap = build_post_match_report(
        conn, team, match_label=args.match, played_on=args.date
    )
    print(f"# Post-match report — {team.name} ({args.match}, {args.date})\n")
    print(recap)

    if not args.no_update:
        before = db.get_dossier(conn, team.id)
        updated = update_dossier_after_match(conn, team, recap)
        print(f"\n# Dossier updated for {team.name}\n")
        if before:
            print(f"## Latest match (before)\n{before.latest_match}\n")
        print(f"## Latest match (after)\n{updated.latest_match}\n")
        print(f"## Rolling form (after)\n{updated.rolling_form}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="worldcup_agents.intelligence")
    sub = parser.add_subparsers(dest="cmd", required=True)
    force_kw = {"action": "store_true", "help": "rebuild even if cached rows exist"}

    p_brief = sub.add_parser("brief", help="build the briefing for one fixture")
    p_brief.add_argument("fixture_id", type=int)
    p_brief.add_argument("--force", **force_kw)
    p_brief.set_defaults(func=_cmd_brief)

    p_dossier = sub.add_parser("dossier", help="build/show one team's dossier")
    p_dossier.add_argument("team_id", type=int)
    p_dossier.add_argument("--force", **force_kw)
    p_dossier.set_defaults(func=_cmd_dossier)

    p_post = sub.add_parser(
        "postmatch", help="recap a finished match and update the team's dossier"
    )
    p_post.add_argument("team_id", type=int)
    p_post.add_argument(
        "--match", required=True, help='e.g. "friendly vs Serbia, won 5-1"'
    )
    p_post.add_argument("--date", required=True, help="date played, e.g. 2026-06-04")
    p_post.add_argument(
        "--no-update",
        action="store_true",
        help="only show the recap; skip the dossier update",
    )
    p_post.set_defaults(func=_cmd_postmatch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
