"""Knockout bracket resolution — fill knockout fixture team ids from results.

The 32 knockout fixtures are seeded with placeholder *labels* only (`"2A"`, `"W73"`,
`"3A/B/C/D/F"`) and `NULL` team ids (DESIGN §3; tasks/todo.md AC#4). Nothing can brief
or settle a knockout match until those labels become real team ids. This module is the
resolver, plugged into the orchestrator tick so it runs automatically as results land.

Resolution is tiered by how authoritative the source is (tasks/todo-bracket.md §2):

  Tier A  `W{n}` / `L{n}`     pure DB — the advancer / non-advancer of fixture n
  Tier B  `1{G}` / `2{G}`     pure DB — computed group standings (FIFA tiebreakers)
  Tier C  `3{candidates}`     computed qualifying-thirds SET + ONE web-fetched official
                              R32 bracket used ONLY for the third-placed→slot assignment,
                              cross-checked against the computed set (web-trust minimized).

Every position slot stays deterministic and verifiable; the single web call only decides
*which* qualifying third pairs with *which* computed anchor. Any disagreement between the
computed backbone and the fetched bracket raises and writes NOTHING — a real conflict is
surfaced for manual review, never papered over.

Temporal integrity (DESIGN §4) holds by construction: R32 resolution is gated on all 72
group matches FINISHED (strictly before any R32 kickoff), and `W{n}`/`L{n}` need fixture n
finished — i.e. a prior round — before the dependent fixture.
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from collections import defaultdict
from typing import Callable, NamedTuple

from . import db
from .config import INTELLIGENCE_MODEL, ModelSpec
from .llm import LLMError, complete, extract_json
from .models import Fixture, MatchStatus, Stage
from .sources.names import normalize

logger = logging.getLogger(__name__)

# Backstop so a pathological dependency never loops forever (5 KO rounds max).
_MAX_FIXPOINT_ITERS = 8


# ---- Group-standings primitives (pure; FIFA ranking, DESIGN §7 / todo-bracket §2B) ----


class _Stat(NamedTuple):
    """A team's standing within a (sub)set of matches."""

    pts: int  # 3/1/0 per win/draw/loss
    gd: int  # goal difference (for − against)
    gf: int  # goals for


def _grouped(fixtures: list[Fixture]) -> dict[str, list[Fixture]]:
    """Group-stage fixtures bucketed by group letter."""
    by_group: dict[str, list[Fixture]] = defaultdict(list)
    for f in fixtures:
        if f.stage == Stage.GROUP and f.group:
            by_group[f.group].append(f)
    return by_group


def _group_team_ids(group_fixtures: list[Fixture]) -> set[int]:
    """Every team id appearing in a group's fixtures (group sides are always resolved)."""
    ids: set[int] = set()
    for f in group_fixtures:
        if f.home_id is not None:
            ids.add(f.home_id)
        if f.away_id is not None:
            ids.add(f.away_id)
    return ids


def _compute_stats(matches: list[Fixture], team_ids: set[int]) -> dict[int, _Stat]:
    """Points / GD / GF for each team over the FINISHED matches in `matches`.

    Teams with no finished match yet appear with zeroed stats (so partial standings
    render during the group stage and a full group ranks all four).
    """
    pts: dict[int, int] = defaultdict(int)
    gf: dict[int, int] = defaultdict(int)
    ga: dict[int, int] = defaultdict(int)
    for f in matches:
        if f.result_90() is None or f.home_id is None or f.away_id is None:
            continue
        hg, ag = f.home_goals_90, f.away_goals_90
        gf[f.home_id] += hg
        ga[f.home_id] += ag
        gf[f.away_id] += ag
        ga[f.away_id] += hg
        if hg > ag:
            pts[f.home_id] += 3
        elif hg < ag:
            pts[f.away_id] += 3
        else:
            pts[f.home_id] += 1
            pts[f.away_id] += 1
    return {t: _Stat(pts[t], gf[t] - ga[t], gf[t]) for t in team_ids}


def _key3(stats: dict[int, _Stat], team_id: int) -> tuple[int, int, int]:
    """Return a team's primary FIFA ranking tuple: points, goal difference, goals."""
    s = stats[team_id]
    return (s.pts, s.gd, s.gf)


def _break_tie(
    tied: list[int], finished: list[Fixture], group: str, warn: bool
) -> list[int]:
    """Order teams tied on (pts, GD, GF) by the head-to-head mini-table, then ascending
    id. A tie surviving H2H needs criteria 5–6 (fair-play / lots) we don't track, so we
    fall back to id and (when `warn`) emit a loud WARNING naming the group."""
    tied_set = set(tied)
    h2h = [f for f in finished if f.home_id in tied_set and f.away_id in tied_set]
    hstats = _compute_stats(h2h, tied_set)
    ordered = sorted(
        tied, key=lambda t: (-hstats[t].pts, -hstats[t].gd, -hstats[t].gf, t)
    )
    if warn:
        for a, b in zip(ordered, ordered[1:]):
            if _key3(hstats, a) == _key3(hstats, b):
                logger.warning(
                    "Group %s: teams %d and %d tied through head-to-head; broken by "
                    "ascending id (fair-play / drawing-of-lots untracked) — review",
                    group,
                    a,
                    b,
                )
    return ordered


def _order_group(
    team_ids: set[int],
    stats: dict[int, _Stat],
    finished: list[Fixture],
    group: str,
    warn: bool,
) -> list[int]:
    """Rank one group 1st→4th: points → GD → GF → head-to-head → ascending id."""
    ids = sorted(team_ids, key=lambda t: (-stats[t].pts, -stats[t].gd, -stats[t].gf, t))
    ordered: list[int] = []
    i = 0
    while i < len(ids):
        j = i + 1
        while j < len(ids) and _key3(stats, ids[j]) == _key3(stats, ids[i]):
            j += 1
        run = ids[i:j]
        if len(run) > 1:
            run = _break_tie(run, finished, group, warn)
        ordered.extend(run)
        i = j
    return ordered


def group_standings(
    fixtures: list[Fixture], *, warn: bool = True
) -> dict[str, list[int]]:
    """Per-group team ids ordered 1st→4th over each group's FINISHED fixtures (pure).

    `warn=False` silences the id-fallback warnings — pass it for the provisional `status`
    view, where partial/zeroed standings tie all the time and the noise is meaningless.
    Keep it on for resolution, where a surviving tie is a real call for manual override.
    """
    out: dict[str, list[int]] = {}
    for group, gfx in _grouped(fixtures).items():
        team_ids = _group_team_ids(gfx)
        finished = [f for f in gfx if f.result_90() is not None]
        stats = _compute_stats(finished, team_ids)
        out[group] = _order_group(team_ids, stats, finished, group, warn)
    return out


def rank_thirds(fixtures: list[Fixture], *, warn: bool = True) -> list[int]:
    """The 12 third-placed teams ranked best→worst by points → GD → GF → ascending id.
    The top 8 qualify for the R32 (FIFA's expanded format). Pure. `warn` as above."""
    standings = group_standings(fixtures, warn=warn)
    thirds: list[tuple[int, _Stat]] = []
    for group, gfx in _grouped(fixtures).items():
        order = standings[group]
        if len(order) < 3:
            continue
        team_ids = _group_team_ids(gfx)
        finished = [f for f in gfx if f.result_90() is not None]
        stats = _compute_stats(finished, team_ids)
        thirds.append((order[2], stats[order[2]]))
    ranked = sorted(thirds, key=lambda x: (-x[1].pts, -x[1].gd, -x[1].gf, x[0]))
    if warn:
        for (ta, sa), (tb, sb) in zip(ranked, ranked[1:]):
            if (sa.pts, sa.gd, sa.gf) == (sb.pts, sb.gd, sb.gf):
                logger.warning(
                    "Third-placed ranking: teams %d and %d tied; broken by ascending id "
                    "(fair-play / drawing-of-lots untracked) — review the top-8 cut",
                    ta,
                    tb,
                )
    return [t for t, _ in ranked]


# ---- Label grammar (pure parsers) ----------------------------------------


def _parse_pos(label: str | None) -> tuple[int, str] | None:
    """`"1A"`/`"2L"` → (position, group); else None."""
    if not label:
        return None
    m = re.fullmatch(r"([12])([A-L])", label)
    return (int(m.group(1)), m.group(2)) if m else None


def _parse_third(label: str | None) -> set[str] | None:
    """`"3A/B/C/D/F"` → {"A","B","C","D","F"} (candidate groups); else None."""
    if not label or not label.startswith("3"):
        return None
    cands = label[1:].split("/")
    if not cands or not all(re.fullmatch(r"[A-L]", c) for c in cands):
        return None
    return set(cands)


def _parse_wl(label: str | None) -> tuple[str, int] | None:
    """`"W74"`/`"L101"` → ("W"|"L", fixture_num); else None."""
    if not label:
        return None
    m = re.fullmatch(r"([WL])(\d+)", label)
    return (m.group(1), int(m.group(2))) if m else None


def winner_of(fixture: Fixture) -> int | None:
    """Team id that advanced from a FINISHED knockout fixture, else None."""
    if fixture.status != MatchStatus.FINISHED:
        return None
    return fixture.advanced_id


def loser_of(fixture: Fixture) -> int | None:
    """The side of a FINISHED knockout fixture that did NOT advance, else None.
    Needs both sides resolved and a known advancer (a level-at-90' game whose advancer
    the result step couldn't confirm leaves `advanced_id=None` → unresolved)."""
    if fixture.status != MatchStatus.FINISHED or fixture.advanced_id is None:
        return None
    sides = {fixture.home_id, fixture.away_id} - {fixture.advanced_id, None}
    return next(iter(sides)) if len(sides) == 1 else None


# ---- Tier A: W{n} / L{n} (pure DB, fixpoint) -----------------------------


def resolve_winner_loser(conn: sqlite3.Connection) -> int:
    """Fill every resolvable `W{n}`/`L{n}` knockout side from `advanced_id`. Returns the
    count of sides filled. A fixpoint loop so a burst of results can cascade R32→Final in
    one tick; idempotent (an already-resolved side is skipped)."""
    filled = 0
    for _ in range(_MAX_FIXPOINT_ITERS):
        changed = 0
        for f in db.list_fixtures(conn):
            updated = False
            for id_attr, label_attr in (
                ("home_id", "home_label"),
                ("away_id", "away_label"),
            ):
                if getattr(f, id_attr) is not None:
                    continue
                wl = _parse_wl(getattr(f, label_attr))
                if wl is None:
                    continue
                kind, src_num = wl
                src = db.get_fixture(conn, src_num)
                if src is None:
                    continue
                tid = winner_of(src) if kind == "W" else loser_of(src)
                if tid is None:
                    continue
                setattr(f, id_attr, tid)
                updated = True
                filled += 1
                changed += 1
            if updated:
                db.upsert_fixture(conn, f)
        if changed == 0:
            break
    return filled


# ---- Tier C: the one web fetch (official R32 bracket) ---------------------

SYSTEM_BRACKET = """You are a meticulous football researcher. You report ONLY verified, \
official fixture pairings from reputable sources (official FIFA, major sports outlets). \
You never guess or infer; if the draw is not yet decided you say so."""

_R32_PROMPT = """Using web search, find the OFFICIAL FIFA World Cup 2026 Round of 32 \
bracket — the 16 fixtures, with the REAL national teams that qualified (group winners, \
runners-up, and the best third-placed teams), now that the group stage has finished.

Respond with ONLY a JSON object, no other text:
{"fixtures": [{"home": "<team>", "away": "<team>"}, ... exactly 16 objects ...]}

Rules:
- Use the official country names (e.g. "USA", "South Korea", "Ivory Coast").
- All 32 teams are real qualified nations — never bracket placeholders like "1A" or "3B".
- If the Round of 32 line-up is not yet officially set, return {"fixtures": []}."""


def fetch_official_r32(
    conn: sqlite3.Connection, *, model: ModelSpec = INTELLIGENCE_MODEL
) -> list[tuple[str, str]]:
    """Web-search the official R32 bracket → 16 (home_name, away_name) pairs. Logs the
    call's telemetry. Raises LLMError if the response is malformed or not 16 fixtures.
    """
    text, call = complete(
        model.model_id,
        _R32_PROMPT,
        model_name=model.name,
        step="bracket",
        system=SYSTEM_BRACKET,
        max_tokens=4000,
        temperature=0.0,
        web_search=True,
    )
    db.log_model_call(conn, call)
    data = extract_json(text)
    raw = data.get("fixtures")
    if not isinstance(raw, list) or len(raw) != 16:
        raise LLMError(f"expected 16 R32 fixtures, got {raw!r}")
    pairs: list[tuple[str, str]] = []
    for item in raw:
        try:
            pairs.append((str(item["home"]), str(item["away"])))
        except (KeyError, TypeError):
            raise LLMError(f"malformed R32 fixture entry {item!r}")
    return pairs


# ---- R32 resolution: positions (Tier B) + cross-checked thirds (Tier C) --


def _pos_team(standings: dict[str, list[int]], pos: int, group: str) -> int | None:
    """Resolve a one-based group position to a team id, if available."""
    order = standings.get(group, [])
    return order[pos - 1] if len(order) >= pos else None


def _web_pairs_to_ids(
    conn: sqlite3.Connection, web: list[tuple[str, str]]
) -> list[tuple[int, int]]:
    """Map the fetched name pairs to team-id pairs. Fails loud listing ALL unmatched
    names (same rule as ingest — a silent drop = a knockout slot wrongly filled)."""
    unmatched: list[str] = []
    pairs: list[tuple[int, int]] = []
    for home, away in web:
        ids: list[int | None] = []
        for name in (home, away):
            tid = None
            try:
                tid = db.team_id_by_name(conn, normalize(name))
            except ValueError:
                tid = None
            if tid is None:
                unmatched.append(name)
            ids.append(tid)
        pairs.append((ids[0], ids[1]))  # type: ignore[arg-type]
    if unmatched:
        raise ValueError(
            f"unmatched team names in official R32 bracket: {sorted(set(unmatched))} "
            "(add an alias in sources/names.py if a name drifted)"
        )
    return pairs


def resolve_r32(
    conn: sqlite3.Connection,
    *,
    fetch: Callable[[sqlite3.Connection], list[tuple[str, str]]] = fetch_official_r32,
) -> int:
    """Fill all 32 R32 sides: position slots from computed standings, third slots from the
    cross-checked official bracket. Returns sides filled. A no-op (no fetch, no writes)
    until all 72 group fixtures are FINISHED or once R32 is already fully resolved.

    Validation is all-or-nothing: any disagreement between the deterministic backbone and
    the fetched bracket raises BEFORE any write, so the DB is never left half-resolved.
    """
    fixtures = db.list_fixtures(conn)
    r32 = [f for f in fixtures if f.stage == Stage.R32]

    # Gate 1 — already resolved? Skip entirely (no wasted web/quota; trap §7).
    if r32 and all(f.home_id is not None and f.away_id is not None for f in r32):
        return 0
    # Gate 2 — group stage must be complete before any R32 slot is knowable.
    groups = [f for f in fixtures if f.stage == Stage.GROUP]
    if not groups or not all(f.status == MatchStatus.FINISHED for f in groups):
        return 0

    standings = group_standings(fixtures)
    qualifying_thirds = set(rank_thirds(fixtures)[:8])
    team_group = {tid: g for g, order in standings.items() for tid in order}

    web_pairs = _web_pairs_to_ids(conn, fetch(conn))
    web_pair_set = {frozenset(p) for p in web_pairs}
    web_by_team: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for h, a in web_pairs:
        web_by_team[h].append((h, a))
        web_by_team[a].append((h, a))

    # Phase 1: validate + compute every fixture's two ids; write nothing yet.
    plan: dict[int, tuple[int, int]] = {}
    for f in r32:
        sides: dict[str, int] = {}
        third_slot: tuple[str, set[str]] | None = None
        for which, label in (("home", f.home_label), ("away", f.away_label)):
            pos = _parse_pos(label)
            third = _parse_third(label)
            if pos is not None:
                tid = _pos_team(standings, pos[0], pos[1])
                if tid is None:
                    raise ValueError(
                        f"R32 fixture {f.id}: cannot resolve position slot {label!r}"
                    )
                sides[which] = tid
            elif third is not None:
                third_slot = (which, third)
            else:
                raise ValueError(f"R32 fixture {f.id}: unparseable label {label!r}")

        if third_slot is None:
            # Both sides are positions — cross-check the pairing against the bracket.
            h, a = sides["home"], sides["away"]
            if frozenset((h, a)) not in web_pair_set:
                raise ValueError(
                    f"R32 fixture {f.id}: computed pairing {h} vs {a} absent from the "
                    "official bracket — refusing to resolve"
                )
            plan[f.id] = (h, a)
        else:
            # Anchor trick: the third is the official opponent of our computed position.
            which, cands = third_slot
            anchor = sides["away" if which == "home" else "home"]
            matches = web_by_team.get(anchor, [])
            if len(matches) != 1:
                raise ValueError(
                    f"R32 fixture {f.id}: anchor team {anchor} appears in "
                    f"{len(matches)} official pairs (expected 1)"
                )
            h, a = matches[0]
            third = a if h == anchor else h
            if third not in qualifying_thirds:
                raise ValueError(
                    f"R32 fixture {f.id}: official third {third} is not in the computed "
                    "top-8 qualifying thirds — refusing to resolve"
                )
            tg = team_group.get(third)
            if tg not in cands:
                raise ValueError(
                    f"R32 fixture {f.id}: third's group {tg!r} not in candidate set "
                    f"{sorted(cands)} for slot {which}"
                )
            sides[which] = third
            plan[f.id] = (sides["home"], sides["away"])

    # Phase 2: everything validated — persist. Count sides newly filled.
    filled = 0
    for f in r32:
        h, a = plan[f.id]
        if f.home_id != h or f.away_id != a:
            filled += (f.home_id is None) + (f.away_id is None)
            f.home_id, f.away_id = h, a
            db.upsert_fixture(conn, f)
    return filled


# ---- Entry point ----------------------------------------------------------


def resolve_brackets(
    conn: sqlite3.Connection,
    *,
    fetch: Callable[[sqlite3.Connection], list[tuple[str, str]]] = fetch_official_r32,
) -> dict[str, int]:
    """Run R32 resolution then the W/L cascade. Returns a counts summary. Called once per
    orchestrator tick (between post-match and brief)."""
    r32 = resolve_r32(conn, fetch=fetch)
    wl = resolve_winner_loser(conn)
    return {"r32": r32, "winner_loser": wl}


# ---- CLI -----------------------------------------------------------------


def _team_label(conn: sqlite3.Connection, tid: int | None, label: str | None) -> str:
    """Return a resolved team name or the fixture's unresolved bracket label."""
    if tid is not None:
        t = db.get_team(conn, tid)
        if t:
            return t.name
    return label or "?"


def _cmd_status(args: argparse.Namespace) -> None:
    """Print provisional group standings and unresolved knockout slots."""
    conn = db.connect()
    db.init_db(conn)
    fixtures = db.list_fixtures(conn)
    standings = group_standings(fixtures, warn=False)  # provisional view — no tie noise
    print("Group standings (over FINISHED group matches only):")
    for g in sorted(standings):
        ranked = "  ".join(
            f"{pos}.{_team_label(conn, tid, None)}"
            for pos, tid in enumerate(standings[g], 1)
        )
        print(f"  {g}: {ranked or '—'}")
    unresolved = [
        f
        for f in fixtures
        if f.stage != Stage.GROUP and (f.home_id is None or f.away_id is None)
    ]
    print(f"\nUnresolved knockout labels ({len(unresolved)}):")
    if not unresolved:
        print("  (none — bracket fully resolved)")
    for f in sorted(unresolved, key=lambda x: x.id):
        h = _team_label(conn, f.home_id, f.home_label)
        a = _team_label(conn, f.away_id, f.away_label)
        print(f"  #{f.id} {f.stage.value}: {h} vs {a}")


def _cmd_resolve(args: argparse.Namespace) -> None:
    """Resolve every currently knowable knockout bracket slot."""
    conn = db.connect()
    db.init_db(conn)
    counts = resolve_brackets(conn)
    print(
        f"Resolved — R32 sides filled: {counts['r32']}, "
        f"W/L sides filled: {counts['winner_loser']}"
    )


def main() -> None:
    """Parse and dispatch the bracket command-line interface."""
    parser = argparse.ArgumentParser(prog="worldcup_agents.bracket")
    sub = parser.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("status", help="show standings + unresolved knockout labels")
    st.set_defaults(func=_cmd_status)

    rs = sub.add_parser("resolve", help="resolve knockout ids from results (acts)")
    rs.set_defaults(func=_cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
