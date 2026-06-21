"""The seven competitors — each a two-step gambler (DESIGN §2, §5).

Every model runs the SAME two steps over the SAME briefing; only the reasoning
engine differs, which is what makes the leaderboard attributable to skill:

    Step 1 PREDICT (odds HIDDEN): briefing -> {winner, confidence, reasoning}
    Step 2 BET     (odds SHOWN) : choose among football-plausible Step-1 outcomes,
                                  then select a fixed conviction tier or pass

The system prompt (the gambler mindset induction) is identical for all seven —
fairness lives there. Odds are withheld until Step 2 so the football judgment is
uninfluenced by the market. At Step 2, odds may choose between outcomes that were already
plausible in the blind forecast, but cannot manufacture a longshot: a pick is eligible only
when its Step-1 probability is within 10 percentage points of the model's top read.

The model OWNS the pick and conviction tier. The engine only enforces eligibility, the
stage's fixed-tier ceiling, and the remaining aggregate-exposure budget. There is no revised
probability, EV gate, Kelly calculation, market blend, or minimum stake floor.
"""

from __future__ import annotations

import argparse
import math
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import db, memory
from .config import (
    BET_ELIGIBILITY_WINDOW,
    BET_STAKE_TIERS,
    MATCHDAY_SHORTFALL_PENALTY_FRACTION,
    MAX_AGGREGATE_EXPOSURE,
    PREDICT_MAX_WORKERS,
    PREDICTION_MODELS,
    ModelSpec,
    stage_cap_fraction,
    stage_matchday_target_fraction,
    stage_stake_tiers,
)
from .experiment import (
    BET_PROMPT_VERSION,
    BETTING_RULES_VERSION,
    EXPERIMENT_PHASE,
    FORECAST_PROMPT_VERSION,
    git_commit,
)
from .llm import LLMError, complete, extract_json
from .models import (
    Bet,
    Fixture,
    MatchBriefing,
    OddsSnapshot,
    Outcome,
    Prediction,
    Stage,
)


class KickoffPassed(RuntimeError):
    """Raised inside predict()/bet() when kickoff arrives mid-call, so nothing is persisted
    after the match has started (temporal integrity for a slow LLM response)."""


@dataclass
class ModelRun:
    """Per-model outcome of run_fixture, so partial fixtures are reported honestly rather
    than counted as fully successful.

    status: "ok" (predicted + bet), "predicted_only" (bet skipped at kickoff),
    "skipped_kickoff" (kickoff already passed before predicting), or "error".
    """

    model_name: str
    status: str
    prediction: Prediction | None = None
    bet: Bet | None = None
    error: str | None = None


# Two system prompts, one per step — both identical across all seven competitors, so the
# only variable under test stays the model (DESIGN §5 "mindset induction").
#
# Step 1 is a NEUTRAL forecaster: the goal is an accurate, well-calibrated read of the
# match, not a bet. It carries no money framing and no upset-seeking. Its probability spread
# is load-bearing downstream — Step 2 may only bet outcomes this forecast rated near the top —
# so the prompt asks for an HONESTLY calibrated spread (decisive when one-sided, close when
# even), never an artificially flat or artificially peaked one.
SYSTEM_FORECASTER = """You are an elite, neutral football analyst forecasting matches at the \
FIFA World Cup 2026. Your only job is to read each match as accurately as it can be read — the \
single most realistic picture of 90 minutes of football, not a bold, contrarian, or \
entertaining take. You are graded on calibration: across many matches, outcomes you call 60% \
likely should come in about 60% of the time.

How you reason:
- Weigh the evidence even-handedly. Do not inflate a side just because it is the favorite, and \
do not reach for an upset because it would be dramatic. The specific facts in the briefing \
decide it — squad quality, current form, who is available, how the two styles interact, what is \
at stake for each side, and the conditions they play in.
- Treat upsets as real but conditional. Genuine leveling factors — an already-qualified side \
resting starters, fatigue or fixture congestion, extreme heat or altitude, a motivation \
mismatch, a stylistic matchup that neutralises the stronger team — matter ONLY when the \
briefing actually supports them. Absent a concrete reason, the stronger, in-form side usually \
wins.
- Make your probability spread mean what it says. A clear mismatch should show a decisive gap \
between the likeliest outcome and the rest; a genuine coin-flip should show the outcomes \
sitting close together. Do not manufacture false certainty, and do not flatten a one-sided game \
into a phantom toss-up — both are calibration failures.
- Keep the scoreline and the result distinct. The likeliest exact score can differ from the \
likeliest outcome — a game can most likely finish 1-1 while a home win is still the most likely \
result — so judge each on its own terms.
- Be decisive and concise. Say what you believe and why, in the plain language of football."""

# Step 2 is the bettor: odds are now visible, but the odds-hidden football read stays the
# guardrail. Eligibility (which outcomes may be backed) and the conviction tiers are computed
# by the engine and injected per match; this system prompt sets the mindset that makes those
# rules feel like discipline rather than a cage.
SYSTEM_GAMBLER = """You are a sharp professional football gambler at the FIFA World Cup 2026, \
competing against six other gamblers. You started with a $1,000,000 virtual bankroll and your \
aim is to grow it across the tournament — but never by betting against your own football \
judgment. Discipline matters, but this is still a betting contest: when your football read is \
clear, you should usually put some money behind it.

The rule that defines you: your odds-hidden Step-1 forecast is the truth you bet from. You may \
only back outcomes your own forecast rated close to your top pick — the bet prompt names \
exactly which outcomes are eligible for this match. This is deliberate: it stops you putting \
real money on a result you yourself judged unlikely just because the price is tempting.

How you decide:
- Read the price against your own read, not the other way round. The odds are there to help you \
choose among outcomes you already found plausible and to judge whether a price is generous, \
fair, or mean — never to talk you onto a longshot you did not believe in. A big payout is not a \
reason to bet; it is the compensation for a risk you must independently judge worth taking.
- In a clear mismatch, a short favourite price is not by itself a reason to pass. If your \
football case is strong, back it at a tier that reflects how strong — a one-sided match you are \
confident in deserves real weight, not a token. Pass only when the market badly overstates the \
side, the matchup contains a concrete football trap, or your own forecast is genuinely thin.
- In a close match, let the price tip you — a co-favourite at a generous number can be the \
smarter bet than the marginal favourite at a short one.
- Passing is allowed, but it should be an active football call, not the default. Never invent \
an angle to force a bet, and never back a side merely because its odds are long.
- Size to your conviction — there is no default tier. You bet in fixed tiers; the bet prompt \
lists the ones open this round, and the full range exists to be used. The right tier is the one \
that matches how strongly your football read AND the price line up: lean on the lower tiers when \
the edge is slim or the price is tight, and step up through the higher tiers as your conviction \
and the value grow — a genuine strong read sized at the floor is money left on the table. The \
floor is still a meaningful bet for a playable but marginal line, not a safe habit; if a line \
does not deserve even that level of risk, the honest answer is to pass.
- Manage the matchday as a portfolio. Each UTC matchday has a target amount of bankroll you \
are expected to allocate across the slate; unallocated target budget is penalized at close. \
You still should not force a bad bet, but if a line is playable, the portfolio target is a \
reason to use a real tier instead of hiding in cash.
- Talk like a pundit, not a quant. Justify every bet from the match itself — form, key \
matchups, tactics, team news, motivation, conditions — then put the price judgment in plain \
words. No talk of expected value, Kelly, edges, or bare percentages.

You are measured on results across the whole tournament, not on eloquence or activity. Be \
decisive, be patient, and protect your bankroll."""

_BET_FORMAT_RETRY_INSTRUCTION = """

FORMAT CORRECTION ONLY:
Your previous answer could not be parsed as JSON. Preserve the same intended pick, stake
tier, and reasoning. Do not reconsider the match. Return ONLY one valid JSON object using
the exact schema requested above, with no markdown fences or surrounding prose.

Your previous malformed answer was:
--- PREVIOUS ANSWER ---
{previous}
--- END PREVIOUS ANSWER ---"""

_BET_REQUEST_RETRY_INSTRUCTION = """

BET REQUEST CORRECTION ONLY:
Your previous JSON parsed, but the requested bet did not satisfy the contract:
{problem}

Do not reconsider the match. Preserve your football reasoning and intended side if it is
legal; otherwise choose PASS. Return ONLY one valid JSON object using this exact schema:
{{"pick": "home" | "draw" | "away" | "pass", "stake_pct": <one of 0, {tiers}>, "reasoning": "<same concise reasoning, adjusted only if needed>"}}

Allowed non-pass picks for this match: {eligible}. If you pass, stake_pct must be 0. If you
bet, stake_pct must be one of the listed non-zero tiers.

Your previous invalid JSON was:
--- PREVIOUS JSON ---
{previous}
--- END PREVIOUS JSON ---"""


def _now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _parse_score(raw: object) -> tuple[int | None, int | None]:
    """Parse a "home-away" scoreline (tolerates -, en-dash, or :) into a pair of ints.

    Returns (None, None) when absent or unparseable — the most-likely score only feeds the
    optional exact-score accuracy point, so a missing one must not fail the whole forecast.
    """
    if not raw:
        return (None, None)
    parts = re.split(r"[-–:]", str(raw).strip(), maxsplit=1)
    if len(parts) != 2:
        return (None, None)
    try:
        h, a = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return (None, None)
    if h < 0 or a < 0:
        return (None, None)
    return (h, a)


def _parse_key_factors(raw: object) -> list[str] | None:
    """Normalise the model's factor tags: short, lowercase, deduplicated strings.

    Lenient — factor tags only feed the report's attribution analysis, so anything
    that isn't a usable list of strings becomes None rather than a failed forecast.
    """
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = " ".join(item.strip().lower().split())[:60]
        if tag and tag not in out:
            out.append(tag)
    return out[:8] or None


# ---- Step 1: PREDICT (odds hidden) ---------------------------------------


def predict(
    conn: sqlite3.Connection,
    model: ModelSpec,
    fixture: Fixture,
    briefing: MatchBriefing,
    home: str,
    away: str,
    *,
    late_update: str | None = None,
    force: bool = False,
) -> Prediction:
    """Step 1: pure football judgment from the briefing, with odds HIDDEN.

    `late_update`, when present, is the near-kickoff delta (confirmed XI / late injuries /
    weather) appended to the briefing the model reads — still facts only, still no odds.
    """
    if not force:
        existing = db.get_prediction(conn, model.name, fixture.id)
        if existing:
            return existing

    late_block = (
        f"\n\n## Late update (near kickoff)\n{late_update}" if late_update else ""
    )
    shared_memory = memory.shared_tournament_memory(conn, fixture)

    is_knockout = fixture.stage != Stage.GROUP
    advance_field = '"advances": "home" | "away", ' if is_knockout else ""
    advance_note = (
        f'\nThis is a KNOCKOUT match: ALSO give "advances" — who ultimately PROGRESSES to '
        f"the next round, counting extra time and penalties ({home}=home, {away}=away). "
        f"Decide this SEPARATELY from the 90-minute result: a side can be the more likely "
        f"90-minute winner yet the less likely to progress over 120 minutes + penalties "
        f"(e.g. a team chasing the tie, or stronger from the spot). Always give your best "
        f"call regardless of your 90-minute score."
        if is_knockout
        else ""
    )

    prompt = f"""MATCH: {home} (home) vs {away} (away) — FIFA World Cup 2026.

Forecast the 90-MINUTE result (extra time and penalties do NOT count). Below is the \
shared, factual briefing. It contains NO betting odds by design — judge on football \
merit alone.

--- BRIEFING ---
{shared_memory}

{briefing.content}{late_block}
--- END BRIEFING ---

Give an explicit probability for each 90-minute outcome (they must sum to ~1.0), your \
expected goals for each side, and the single most-likely exact scoreline.

Respond with ONLY a JSON object, no other text:
{{"p_home": <0.0-1.0>, "p_draw": <0.0-1.0>, "p_away": <0.0-1.0>, \
"expected_home_goals": <float ≥ 0>, "expected_away_goals": <float ≥ 0>, \
"most_likely_score": "<home>-<away>", {advance_field}"key_factors": [<3-6 short \
lowercase tags>], "reasoning": "<4-8 sentences walking through how you weighed the \
evidence and reached this forecast>"}}
p_home/p_draw/p_away are the probabilities of {home} winning, a draw, and {away} winning \
after 90 minutes; calibrate them honestly. most_likely_score is the single likeliest 90' \
scoreline — it may differ from the most probable outcome, which is fine. key_factors \
names the factors that actually drove your forecast, as short lowercase tags (examples: \
"injuries", "rest advantage", "altitude", "motivation mismatch", "tactical matchup", \
"form", "home crowd").{advance_note}"""

    text, call = complete(
        model.model_id,
        prompt,
        model_name=model.name,
        step="predict",
        fixture_id=fixture.id,
        system=SYSTEM_FORECASTER,
        max_tokens=25000,  # generous — let reasoning models think freely, never capped
        temperature=0.5,
        reasoning_effort="high",  # don't compromise reasoning quality
    )
    db.log_model_call(conn, call)

    data = extract_json(text)

    def _prob(key: str) -> float:
        """Read one finite, non-negative probability from the model response."""
        try:
            v = float(data[key])
        except (KeyError, ValueError, TypeError):
            raise LLMError(f"{model.name}: invalid/missing {key} in {data!r}")
        # Python's json.loads accepts NaN/Infinity — reject them before they poison the
        # normalisation (NaN would propagate; inf would make every other prob normalise to 0).
        if not math.isfinite(v):
            raise LLMError(f"{model.name}: non-finite {key}={v!r} in {data!r}")
        return max(0.0, v)

    total = _prob("p_home") + _prob("p_draw") + _prob("p_away")
    if total <= 0:
        raise LLMError(f"{model.name}: 1X2 probabilities sum to 0 in {data!r}")
    # Normalise so the distribution sums to exactly 1 regardless of how the model rounded.
    p_home = _prob("p_home") / total
    p_draw = _prob("p_draw") / total
    p_away = _prob("p_away") / total
    probs = {Outcome.HOME: p_home, Outcome.DRAW: p_draw, Outcome.AWAY: p_away}

    # Winner = argmax of the distribution (stable tie-break: home > draw > away). This is
    # now the single source of truth for the outcome — not the most-likely scoreline.
    winner = max((Outcome.HOME, Outcome.DRAW, Outcome.AWAY), key=lambda o: probs[o])
    confidence = probs[winner]

    # Most-likely scoreline + expected goals are context (optional, never block a forecast).
    pred_home_goals, pred_away_goals = _parse_score(data.get("most_likely_score"))

    def _xg(key: str) -> float | None:
        """Read an optional finite, non-negative expected-goals value."""
        try:
            v = float(data[key])
        except (KeyError, ValueError, TypeError):
            return None
        return v if (math.isfinite(v) and v >= 0) else None

    exp_home_goals, exp_away_goals = _xg("expected_home_goals"), _xg(
        "expected_away_goals"
    )

    # Knockouts: who advances. Always taken from the model's EXPLICIT call (not derived from
    # the 90' winner) — a side can be the 90' favourite yet less likely to progress over
    # ET + penalties, so the two are predicted independently.
    predicted_advance: Outcome | None = None
    if is_knockout:
        adv = str(data.get("advances", "")).strip().lower()
        if adv not in {"home", "away"}:
            raise LLMError(
                f"{model.name}: knockout needs 'advances' home/away in {data!r}"
            )
        predicted_advance = Outcome.HOME if adv == "home" else Outcome.AWAY

    reasoning = str(data.get("reasoning", "")).strip()

    # Factor tags are report material (factor-attribution analysis) — optional and
    # lenient by design: anything garbled becomes None, never a failed forecast.
    key_factors = _parse_key_factors(data.get("key_factors"))

    # Kickoff guard (P1-3): a slow response can arrive after KO — never persist a prediction
    # for a match that has already started.
    if _now() >= fixture.kickoff:
        raise KickoffPassed(
            f"{model.name}: kickoff passed before predicting {fixture.id}"
        )

    pred = Prediction(
        model_name=model.name,
        fixture_id=fixture.id,
        winner=winner,
        p_home=p_home,
        p_draw=p_draw,
        p_away=p_away,
        pred_home_goals=pred_home_goals,
        pred_away_goals=pred_away_goals,
        exp_home_goals=exp_home_goals,
        exp_away_goals=exp_away_goals,
        predicted_advance=predicted_advance,
        confidence=confidence,
        reasoning=reasoning,
        key_factors=key_factors,
        experiment_phase=EXPERIMENT_PHASE,
        prompt_version=FORECAST_PROMPT_VERSION,
        requested_model_id=model.model_id,
        call_generation_id=call.generation_id,
        git_commit=git_commit(),
        created_at=_now(),
    )
    db.upsert_prediction(conn, pred)
    return pred


# ---- Step 2: BET (odds shown) --------------------------------------------


def _odds_for(odds: OddsSnapshot, pick: Outcome) -> float:
    """Return the decimal price corresponding to a selected 1X2 outcome."""
    return {Outcome.HOME: odds.home, Outcome.DRAW: odds.draw, Outcome.AWAY: odds.away}[
        pick
    ]


def _prediction_probabilities(prediction: Prediction) -> dict[Outcome, float]:
    """Return the immutable blind Step-1 distribution used by the eligibility gate.

    New predictions always have a complete distribution. The winner-only fallback keeps
    legacy rows usable without letting an unrecorded probability authorize another pick.
    """
    if prediction.has_distribution:
        return {
            Outcome.HOME: prediction.p_home,
            Outcome.DRAW: prediction.p_draw,
            Outcome.AWAY: prediction.p_away,
        }
    return {prediction.winner: prediction.confidence}


def _eligible_outcomes(prediction: Prediction) -> dict[Outcome, float]:
    """Outcomes within the configured probability window of the blind top read."""
    probabilities = _prediction_probabilities(prediction)
    top = max(probabilities.values())
    return {
        outcome: probability
        for outcome, probability in probabilities.items()
        if top - probability <= BET_ELIGIBILITY_WINDOW + 1e-12
    }


def _parse_stake_fraction(raw: object) -> float | None:
    """Normalize `10`, `"10%"`, or `0.10` to a finite non-negative fraction."""
    if isinstance(raw, str):
        raw = raw.strip().removesuffix("%").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if value > 1:
        value /= 100
    return value


def _parse_stake_tier(raw: object) -> float | None:
    """Parse a requested percentage into one of the fixed global stake tiers.

    Returns the fraction form (`0.10`). Zero is reserved for a pass. Arbitrary
    percentages fail closed instead of being rounded to a tier.
    """
    value = _parse_stake_fraction(raw)
    if value is None:
        return None
    if abs(value) <= 1e-12:
        return 0.0
    return next(
        (tier for tier in BET_STAKE_TIERS if abs(value - tier) <= 1e-9),
        None,
    )


def _parse_bet_request(data: dict, bankroll: float) -> dict[str, object]:
    """Normalize a model's requested bet and flag contract-level request errors."""
    raw_pick = str(data.get("pick", "pass")).strip().lower()
    pick = Outcome(raw_pick) if raw_pick in {"home", "draw", "away"} else None
    raw_tier = data.get("stake_pct", 0)
    requested_fraction = _parse_stake_fraction(raw_tier)
    tier = _parse_stake_tier(raw_tier)

    invalid_request = raw_pick not in {"home", "draw", "away", "pass"}
    invalid_tier = tier is None
    if tier is None:
        tier = 0.0
    if not invalid_tier and (
        (raw_pick == "pass" and tier > 0) or (pick is not None and tier <= 0)
    ):
        invalid_request = True

    return {
        "raw_pick": raw_pick,
        "pick": pick,
        "raw_tier": raw_tier,
        "requested_fraction": requested_fraction,
        "tier": tier,
        "invalid_request": invalid_request,
        "invalid_tier": invalid_tier,
        "requested_pick": pick,
        "requested_stake": bankroll * (requested_fraction or 0.0),
    }


def _bet_request_problem(
    parsed: dict[str, object], available_tiers: tuple[float, ...]
) -> str:
    """Human-readable explanation for one semantic correction retry."""
    tiers = "0, " + ", ".join(f"{tier * 100:.0f}" for tier in available_tiers)
    raw_pick = parsed["raw_pick"]
    raw_tier = parsed["raw_tier"]
    if parsed["invalid_tier"]:
        return f"stake_pct must be one of {tiers}; you gave {raw_tier!r}."
    return (
        "pick and stake_pct must agree: pass uses stake_pct 0, and a non-pass pick "
        f"uses one listed non-zero tier. You gave pick={raw_pick!r}, stake_pct={raw_tier!r}."
    )


def _exposure_note(bankroll: float, open_stake: float, open_count: int) -> str:
    """One line telling the agent how much of its bankroll is already committed to other
    matches still awaiting a result, so it can size against its FREE balance instead of the
    gross bankroll. Empty when nothing is open. The engine separately enforces the 50%
    aggregate-exposure ceiling after the model chooses its tier."""
    if open_stake <= 0 or open_count <= 0:
        return ""
    free = max(0.0, bankroll - open_stake)
    matches = "match" if open_count == 1 else "matches"
    return (
        f" NOTE: you already have ${open_stake:,.0f} staked on {open_count} other "
        f"{matches} still awaiting a result, so your free (uncommitted) bankroll is about "
        f"${free:,.0f}. Size this bet against that free balance — simultaneous matches "
        f"share one bankroll, so don't over-commit across them."
    )


def _matchday_portfolio_note(
    conn: sqlite3.Connection, fixture: Fixture, model_name: str, bankroll: float
) -> str:
    """Explain the slate-level allocation target that will be enforced at day close."""
    matchday = fixture.kickoff.date().isoformat()
    target_fraction = stage_matchday_target_fraction(fixture.stage.value)
    staked_today = db.staked_by_model_on(conn, matchday).get(model_name, 0.0)
    target = bankroll * target_fraction
    remaining = max(0.0, target - staked_today)
    if remaining <= 0:
        return (
            f"\nMATCHDAY PORTFOLIO: your {matchday} target allocation is "
            f"{target_fraction:.0%} of bankroll (${target:,.0f}), and you have already "
            f"allocated about ${staked_today:,.0f}. You have met the target; bet this "
            f"fixture only if the football case still deserves additional risk."
        )
    penalty = remaining * MATCHDAY_SHORTFALL_PENALTY_FRACTION
    return (
        f"\nMATCHDAY PORTFOLIO: your {matchday} target allocation is "
        f"{target_fraction:.0%} of bankroll (${target:,.0f}) across today's fixtures. "
        f"You have already allocated about ${staked_today:,.0f}, leaving about "
        f"${remaining:,.0f} before the target is met. Any unallocated target budget at "
        f"matchday close loses {MATCHDAY_SHORTFALL_PENALTY_FRACTION:.0%} "
        f"(${penalty:,.0f} if you make no further bets). Passing is allowed, but only "
        f"when this line is worse than paying that shortfall cost."
    )


def bet(
    conn: sqlite3.Connection,
    model: ModelSpec,
    fixture: Fixture,
    prediction: Prediction,
    odds: OddsSnapshot,
    bankroll: float,
    home: str,
    away: str,
    *,
    force: bool = False,
) -> Bet:
    """Step 2: choose an eligible outcome and fixed stake tier, or pass."""
    if not force:
        existing = db.get_bet(conn, model.name, fixture.id)
        if existing:
            return existing

    cap_fraction = stage_cap_fraction(fixture.stage.value)
    available_tiers = stage_stake_tiers(fixture.stage.value)
    eligible = _eligible_outcomes(prediction)

    # What this model has already committed to other still-unsettled matches. This
    # read-then-write is not atomic. The live timer processes fixtures sequentially, so a
    # model never bets two fixtures at once and the 50% cap holds; concurrent manual runs
    # could each read the same exposure and jointly exceed it.
    open_stake, open_count = db.open_exposure(conn, model.name)
    exposure_note = _exposure_note(bankroll, open_stake, open_count)
    portfolio_note = _matchday_portfolio_note(conn, fixture, model.name, bankroll)

    if prediction.has_distribution:
        forecast_line = (
            f"  your 90' probabilities: home {prediction.p_home:.0%} · "
            f"draw {prediction.p_draw:.0%} · away {prediction.p_away:.0%}\n"
            f"  (most likely: {prediction.winner.value}, confidence "
            f"{prediction.confidence:.0%})"
        )
    else:
        forecast_line = f"  winner={prediction.winner.value}, confidence={prediction.confidence:.2f}"

    names = {
        Outcome.HOME: f"home ({home})",
        Outcome.DRAW: "draw",
        Outcome.AWAY: f"away ({away})",
    }
    eligible_line = ", ".join(
        f"{names[outcome]} {probability:.0%}"
        for outcome, probability in eligible.items()
    )
    tier_line = ", ".join(f"{tier:.0%}" for tier in available_tiers)
    bet_memory = memory.betting_memory_block(conn, model.name, fixture)

    prompt = f"""MATCH: {home} (home) vs {away} (away) — 90-minute result.

--- MEMORY ---
{bet_memory}
--- END MEMORY ---

YOUR earlier forecast (odds were hidden then):
{forecast_line}
  reasoning: {prediction.reasoning}

NOW the market 1X2 decimal odds (payout = stake x odds on a win):
  home ({home}): {odds.home}
  draw:          {odds.draw}
  away ({away}): {odds.away}

Your blind forecast is the football guardrail. An outcome is eligible only when its Step-1 \
probability is within {BET_ELIGIBILITY_WINDOW:.0%} of your top read. For this match, the ONLY \
eligible outcomes are: {eligible_line}. You may use the prices to choose among those outcomes, \
or PASS. Any other pick will be rejected. Do not invent a case just to wager, and do not choose \
a longshot solely because its payout is large.

If you back an outcome, size the tier to your conviction — how strongly your read and the price \
line up. There is no default tier and the floor is not a safe habit: the full ladder below is \
there to be used, and a strong read backed at the minimum is value left on the table. Reserve \
the floor for genuinely marginal but playable calls; 5% is still a meaningful bet, so do not \
pass merely because the line does not justify 10% or more. When a bet does not deserve even \
the floor, pass outright rather than shrinking it to a token.

Choose one fixed conviction tier for this {fixture.stage.value} match: {tier_line}. The stage \
ceiling is {cap_fraction:.0%} of bankroll. A tier is a percentage of your current \
${bankroll:,.0f} bankroll; the engine may trim it only when your aggregate live exposure is \
already near 50%.{exposure_note}{portfolio_note}

Respond with ONLY a JSON object, no other text:
{{"pick": "home" | "draw" | "away" | "pass", \
"stake_pct": <one of 0, {", ".join(f"{tier * 100:.0f}" for tier in available_tiers)}>, \
"reasoning": "<2-5 sentences a football fan would enjoy: tell the match story (form, key \
matchups, tactics, team news) and why the selected eligible outcome is or is not worth its \
price, then why this conviction tier fits. Lead with football, not formulas>"}}"""

    # A malformed response gets one format-only retry. A parsed but contract-invalid request
    # then gets one correction retry; ineligible football picks still fail closed below.
    # Every call is logged, and the final Bet links to the accepted/final attempt.
    retry_prompt = prompt
    data: dict | None = None
    call = None
    for attempt in range(2):
        text, call = complete(
            model.model_id,
            retry_prompt,
            model_name=model.name,
            step="bet",
            fixture_id=fixture.id,
            system=SYSTEM_GAMBLER,
            max_tokens=25000,
            temperature=0.5,
            reasoning_effort="high",
        )
        db.log_model_call(conn, call)
        try:
            data = extract_json(text)
            break
        except LLMError:
            if attempt == 1:
                raise
            if _now() >= fixture.kickoff:
                raise KickoffPassed(
                    f"{model.name}: kickoff passed before retrying bet {fixture.id}"
                )
            retry_prompt = prompt + _BET_FORMAT_RETRY_INSTRUCTION.format(
                previous=text[:2000]
            )

    assert data is not None and call is not None
    parsed = _parse_bet_request(data, bankroll)
    if parsed["invalid_tier"] or parsed["invalid_request"]:
        if _now() >= fixture.kickoff:
            raise KickoffPassed(
                f"{model.name}: kickoff passed before correcting bet {fixture.id}"
            )
        problem = _bet_request_problem(parsed, available_tiers)
        retry_prompt = prompt + _BET_REQUEST_RETRY_INSTRUCTION.format(
            problem=problem,
            tiers=", ".join(f"{tier * 100:.0f}" for tier in available_tiers),
            eligible=eligible_line,
            previous=str(data)[:2000],
        )
        text, call = complete(
            model.model_id,
            retry_prompt,
            model_name=model.name,
            step="bet",
            fixture_id=fixture.id,
            system=SYSTEM_GAMBLER,
            max_tokens=25000,
            temperature=0.5,
            reasoning_effort="high",
        )
        db.log_model_call(conn, call)
        data = extract_json(text)
        parsed = _parse_bet_request(data, bankroll)

    reasoning = str(data.get("reasoning", "")).strip()
    pick = parsed["pick"]
    tier = parsed["tier"]
    invalid_request = bool(parsed["invalid_request"])
    invalid_tier = bool(parsed["invalid_tier"])

    requested_pick = parsed["requested_pick"]
    requested_stake = parsed["requested_stake"]
    engine_adjustment: str | None = None

    if invalid_tier:
        engine_adjustment = "invalid_tier"
        pick = None
    elif invalid_request:
        engine_adjustment = "invalid_request"
        pick = None
    elif pick is not None and pick not in eligible:
        top = max(_prediction_probabilities(prediction).values())
        probability = _prediction_probabilities(prediction).get(pick, 0.0)
        gap = top - probability
        reasoning = (
            f"{reasoning}  [auto-pass: {pick.value} was {gap:.0%} below the blind "
            f"top read, outside the {BET_ELIGIBILITY_WINDOW:.0%} eligibility window]"
        ).strip()
        engine_adjustment = "ineligible_pick"
        pick = None

    stake = 0.0
    if pick is not None:
        capped_tier = min(tier, cap_fraction)
        if capped_tier < tier:
            engine_adjustment = "stage_cap"
        stage_stake = bankroll * capped_tier
        remaining_exposure = max(0.0, bankroll * MAX_AGGREGATE_EXPOSURE - open_stake)
        stake = min(stage_stake, remaining_exposure)
        if stake < stage_stake:
            engine_adjustment = "exposure_cap"
        if stake <= 0:
            pick = None

    if pick is None or stake <= 0:
        result = Bet(
            model_name=model.name,
            fixture_id=fixture.id,
            pick=None,
            stake=0.0,
            odds_at_bet=None,
            requested_pick=requested_pick,
            requested_stake=requested_stake,
            engine_adjustment=engine_adjustment,
            reasoning=reasoning,
            experiment_phase=EXPERIMENT_PHASE,
            prompt_version=BET_PROMPT_VERSION,
            rules_version=BETTING_RULES_VERSION,
            requested_model_id=model.model_id,
            call_generation_id=call.generation_id,
            git_commit=git_commit(),
            odds_snapshot_bookmaker=odds.bookmaker,
            odds_snapshot_captured_at=odds.captured_at,
            created_at=_now(),
        )
    else:
        result = Bet(
            model_name=model.name,
            fixture_id=fixture.id,
            pick=pick,
            stake=round(stake, 2),
            odds_at_bet=_odds_for(odds, pick),
            requested_pick=requested_pick,
            requested_stake=requested_stake,
            engine_adjustment=engine_adjustment,
            reasoning=reasoning,
            experiment_phase=EXPERIMENT_PHASE,
            prompt_version=BET_PROMPT_VERSION,
            rules_version=BETTING_RULES_VERSION,
            requested_model_id=model.model_id,
            call_generation_id=call.generation_id,
            git_commit=git_commit(),
            odds_snapshot_bookmaker=odds.bookmaker,
            odds_snapshot_captured_at=odds.captured_at,
            created_at=_now(),
        )

    # Kickoff guard (P1-3): never persist a bet after the match has started.
    if _now() >= fixture.kickoff:
        raise KickoffPassed(f"{model.name}: kickoff passed before betting {fixture.id}")
    db.upsert_bet(conn, result)
    return result


# ---- Orchestration -------------------------------------------------------


def _record_pass(
    conn: sqlite3.Connection,
    model: ModelSpec,
    fixture: Fixture,
    reason: str,
    odds: OddsSnapshot | None = None,
    *,
    force: bool = False,
) -> Bet:
    """Persist an explicit pass (no LLM call). Used for eliminated competitors, whose bets
    are disabled but whose predictions still run for the accuracy board."""
    if not force:
        existing = db.get_bet(conn, model.name, fixture.id)
        if existing:
            return existing
    b = Bet(
        model_name=model.name,
        fixture_id=fixture.id,
        pick=None,
        stake=0.0,
        odds_at_bet=None,
        engine_adjustment="eliminated",
        reasoning=reason,
        experiment_phase=EXPERIMENT_PHASE,
        prompt_version=BET_PROMPT_VERSION,
        rules_version=BETTING_RULES_VERSION,
        requested_model_id=model.model_id,
        git_commit=git_commit(),
        odds_snapshot_bookmaker=odds.bookmaker if odds else None,
        odds_snapshot_captured_at=odds.captured_at if odds else None,
        created_at=_now(),
    )
    db.upsert_bet(conn, b)
    return b


def run_fixture(
    conn: sqlite3.Connection, fixture_id: int, *, force: bool = False
) -> list[ModelRun]:
    """Run all competitors through both steps for one fixture (idempotent, concurrent).

    Returns one ModelRun per competitor (always len == PREDICTION_MODELS) carrying each
    model's status, so the caller can report partial fixtures honestly rather than treating
    any return as full success.
    """
    fixture = db.get_fixture(conn, fixture_id)
    if fixture is None:
        raise ValueError(f"no fixture with id {fixture_id}")
    briefing = db.get_match_briefing(conn, fixture_id)
    if briefing is None:
        raise ValueError(
            f"no briefing for fixture {fixture_id} — run "
            f"`python -m worldcup_agents.intelligence brief {fixture_id}` first"
        )
    odds = db.consensus_odds(conn, fixture_id)
    if odds is None:
        raise ValueError(
            f"no consensus odds for fixture {fixture_id} — run "
            "`python -m worldcup_agents.ingest odds` first"
        )

    home = db.get_team(conn, fixture.home_id).name
    away = db.get_team(conn, fixture.away_id).name

    # Near-kickoff delta (built best-effort by the orchestrator just before this); every
    # model reads the SAME late update appended to the SAME briefing — shared facts intact.
    late = db.get_late_update(conn, fixture_id)
    late_content = late.content if late else None

    # Each model's predict+bet is independent. On a busy matchday several fixtures kick off
    # together (e.g. the final group round), so run the models CONCURRENTLY — bounded — to
    # fit the tight pre-kickoff window. sqlite connections aren't thread-safe, so each worker
    # opens its OWN on the same db file (works for the live DB and throwaway test DBs alike).
    db_path = conn.execute("PRAGMA database_list").fetchone()["file"]

    def _run_one(model: ModelSpec) -> ModelRun:
        """Run one competitor independently with its own SQLite connection."""
        own = db.connect(db_path) if db_path else conn
        try:
            # Never start after kickoff: a long tick, or a fixture queued behind others,
            # can drift past KO — re-check right before the slow calls.
            if _now() >= fixture.kickoff:
                return ModelRun(model.name, "skipped_kickoff")
            comp = db.get_competitor(own, model.name)
            active = comp.active if comp else True
            bankroll = comp.bankroll if comp else 0.0
            try:
                pred = predict(
                    own,
                    model,
                    fixture,
                    briefing,
                    home,
                    away,
                    late_update=late_content,
                    force=force,
                )
            except KickoffPassed:
                return ModelRun(model.name, "skipped_kickoff")
            # Eliminated competitors (P2-3): keep predicting for the accuracy board, but
            # betting is disabled — record an explicit pass instead of calling the bet model.
            if not active:
                b = _record_pass(
                    own,
                    model,
                    fixture,
                    "eliminated — betting disabled",
                    odds,
                    force=force,
                )
                return ModelRun(model.name, "ok", pred, b)
            try:
                b = bet(
                    own, model, fixture, pred, odds, bankroll, home, away, force=force
                )
            except KickoffPassed:
                return ModelRun(model.name, "predicted_only", pred, None)
            return ModelRun(model.name, "ok", pred, b)
        except (
            Exception
        ) as e:  # noqa: BLE001 - capture per-model failure; never abort others
            return ModelRun(model.name, "error", error=f"{type(e).__name__}: {e}")
        finally:
            if db_path:
                own.close()

    if db_path and PREDICT_MAX_WORKERS > 1:
        with ThreadPoolExecutor(max_workers=PREDICT_MAX_WORKERS) as ex:
            return list(ex.map(_run_one, PREDICTION_MODELS))
    return [_run_one(m) for m in PREDICTION_MODELS]


# ---- CLI -----------------------------------------------------------------


def format_reasoning(
    fixture_id: int,
    home: str,
    away: str,
    results: list[tuple[Prediction, Bet]],
) -> str:
    """Markdown of every model's full Step-1 + Step-2 thought process."""
    lines = [f"# Reasoning — fixture {fixture_id}: {home} vs {away}\n"]
    for pred, b in results:
        pick = b.pick.value if b.pick else "pass"
        stake = f"${b.stake:,.0f}" + (
            f" @ {b.odds_at_bet:.2f}" if b.odds_at_bet else ""
        )
        adjustment = f" · engine: {b.engine_adjustment}" if b.engine_adjustment else ""
        score = (
            f" {pred.pred_home_goals}-{pred.pred_away_goals}" if pred.has_score else ""
        )
        advance = (
            f" · advances: {pred.predicted_advance.value}"
            if pred.predicted_advance
            else ""
        )
        lines.append(f"## {pred.model_name}")
        lines.append(
            f"**Predict:** {pred.winner.value}{score}{advance} "
            f"(confidence {pred.confidence:.2f}) · **Bet:** {pick} {stake}{adjustment}\n"
        )
        lines.append(
            f"**Step 1 — prediction reasoning (odds hidden):**\n\n{pred.reasoning}\n"
        )
        lines.append(f"**Step 2 — bet reasoning (odds shown):**\n\n{b.reasoning}\n")
    return "\n".join(lines)


def _cmd_predict(args: argparse.Namespace) -> None:
    """Run and display every model's prediction and bet for one fixture."""
    conn = db.connect()
    db.init_db(conn)
    runs = run_fixture(conn, args.fixture_id, force=args.force)
    fixture = db.get_fixture(conn, args.fixture_id)
    home = db.get_team(conn, fixture.home_id).name
    away = db.get_team(conn, fixture.away_id).name
    print(f"Fixture {args.fixture_id}: {home} vs {away}\n")
    print(
        f"{'model':<18}{'predict':<8}{'score':>6}{'conf':>7}"
        f"{'bet':>7}{'stake':>12}{'odds':>7}{'engine':>18}"
    )
    completed = [(r.prediction, r.bet) for r in runs if r.status == "ok"]
    for pred, b in completed:
        pick = b.pick.value if b.pick else "pass"
        odds = f"{b.odds_at_bet:.2f}" if b.odds_at_bet else "—"
        score = (
            f"{pred.pred_home_goals}-{pred.pred_away_goals}" if pred.has_score else "—"
        )
        adjustment = b.engine_adjustment or "—"
        print(
            f"{pred.model_name:<18}{pred.winner.value:<8}{score:>6}{pred.confidence:>7.2f}"
            f"{pick:>7}{b.stake:>12,.0f}{odds:>7}{adjustment:>18}"
        )
    # Report any model that did not fully complete (P1-4) — never hide a partial run.
    incomplete = [r for r in runs if r.status != "ok"]
    if incomplete:
        print(f"\nIncomplete ({len(incomplete)}/{len(runs)}):")
        for r in incomplete:
            print(f"  {r.model_name:<18}{r.status}{f' — {r.error}' if r.error else ''}")

    if args.reasons:
        md = format_reasoning(args.fixture_id, home, away, completed)
        print("\n" + md)
        out = Path(".cache") / f"reasoning-fixture-{args.fixture_id}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"\n(saved to {out})")


def main() -> None:
    """Parse and dispatch the prediction command-line interface."""
    parser = argparse.ArgumentParser(prog="worldcup_agents.predict")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict", help="run all models' predict+bet for a fixture")
    p.add_argument("fixture_id", type=int)
    p.add_argument(
        "--force", action="store_true", help="re-run even if predictions/bets exist"
    )
    p.add_argument(
        "--reasons",
        action="store_true",
        help="print each model's full reasoning and save it to .cache/",
    )
    p.set_defaults(func=_cmd_predict)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
