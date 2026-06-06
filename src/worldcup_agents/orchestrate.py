"""Orchestrator — the scheduled tick that drives the whole pipeline (DESIGN §11).

A coarse, idempotent pass invoked by a systemd timer (or cron). It reads "what is
due now" from fixture kickoff times + DB state and fans the work out IN ORDER so
temporal integrity holds (DESIGN §4): finished matches are settled and folded into
the dossiers BEFORE upcoming matches are briefed, so post-match facts from match N
reach match N+1's briefing and never its own.

    tick(now):
      1. ingest results   matches past kickoff + RESULT_DELAY, still unresolved
      2. settle bets      resolved fixtures that still have unsettled bets
      3. post-match       finished fixtures -> per-team recap + dossier fold (once/team)
      4. resolve bracket  fill knockout team ids from finished results (gates briefing)
      5. idle decay       matchdays fully closed and not yet decayed
      6. brief            scheduled fixtures inside the pre-match window (no briefing yet)
      7. predict + bet    scheduled fixtures inside the bet window (briefing + odds present)

Every stage is lazy/idempotent, so the tick is safe to run on any cadence and to
overlap or resume after a crash. Per-fixture failures are caught and logged so one
bad match never blocks the rest of the tournament. Odds polling is intentionally a
SEPARATE, less-frequent job (`ingest odds`): a global, quota-limited external poll —
the tick consumes whatever odds exist and waits to bet a fixture until they're present.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import bracket, db, intelligence, predict, results, settlement
from .config import (
    BET_LEAD_HOURS,
    BRIEF_LEAD_HOURS,
    PREDICTION_MODELS,
    RESULT_DELAY_HOURS,
)
from .models import Fixture, MatchStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hours_until(kickoff: datetime, now: datetime) -> float:
    return (kickoff - now).total_seconds() / 3600.0


# ---- "What is due now" selectors (deterministic; offline-testable) -------


def due_for_result(fixtures: list[Fixture], now: datetime) -> list[Fixture]:
    """Unresolved fixtures whose kickoff + RESULT_DELAY has passed."""
    cutoff = timedelta(hours=RESULT_DELAY_HOURS)
    return [
        f
        for f in fixtures
        if f.status not in (MatchStatus.FINISHED, MatchStatus.POSTPONED)
        and now >= f.kickoff + cutoff
    ]


def due_for_settle(conn: sqlite3.Connection, fixtures: list[Fixture]) -> list[Fixture]:
    """Resolved fixtures that still have at least one unsettled bet."""
    out = []
    for f in fixtures:
        if f.status not in (MatchStatus.FINISHED, MatchStatus.POSTPONED):
            continue
        bets = db.list_bets(conn, f.id)
        if any(db.get_settlement(conn, b.model_name, f.id) is None for b in bets):
            out.append(f)
    return out


def due_for_postprocess(
    conn: sqlite3.Connection, fixtures: list[Fixture]
) -> list[Fixture]:
    """Finished fixtures (real 90' result) with at least one team's dossier unfolded."""
    out = []
    for f in fixtures:
        if f.status != MatchStatus.FINISHED or f.result_90() is None:
            continue
        teams = [t for t in (f.home_id, f.away_id) if t is not None]
        if any(not db.dossier_folded(conn, f.id, t) for t in teams):
            out.append(f)
    return out


def due_matchdays(conn: sqlite3.Connection, fixtures: list[Fixture]) -> list[str]:
    """UTC dates whose every fixture is resolved and which haven't been decayed yet."""
    days: dict[str, list[Fixture]] = defaultdict(list)
    for f in fixtures:
        days[f.kickoff.date().isoformat()].append(f)
    out = []
    for day, fs in sorted(days.items()):
        resolved = all(
            f.status in (MatchStatus.FINISHED, MatchStatus.POSTPONED) for f in fs
        )
        if resolved and not db.matchday_decayed(conn, day):
            out.append(day)
    return out


def due_for_brief(
    conn: sqlite3.Connection, fixtures: list[Fixture], now: datetime
) -> list[Fixture]:
    """Scheduled fixtures inside the pre-match window that have no briefing yet."""
    out = []
    for f in fixtures:
        if f.status != MatchStatus.SCHEDULED:
            continue
        h = _hours_until(f.kickoff, now)
        if 0 <= h <= BRIEF_LEAD_HOURS and db.get_match_briefing(conn, f.id) is None:
            out.append(f)
    return out


def due_for_bet(
    conn: sqlite3.Connection, fixtures: list[Fixture], now: datetime
) -> list[Fixture]:
    """Scheduled fixtures inside the bet window with a briefing AND odds present, where
    not every competitor has bet yet. (Predict + bet run together — predictions are
    judged with odds hidden, then the bet sees them, all before kickoff.)"""
    out = []
    for f in fixtures:
        if f.status != MatchStatus.SCHEDULED:
            continue
        h = _hours_until(f.kickoff, now)
        if not (0 <= h <= BET_LEAD_HOURS):
            continue
        if db.get_match_briefing(conn, f.id) is None:
            continue
        if db.consensus_odds(conn, f.id) is None:
            continue  # wait for the odds poller — never block, just defer
        if len(db.list_bets(conn, f.id)) < len(PREDICTION_MODELS):
            out.append(f)
    return out


# ---- Post-match: per-team recap + guarded dossier fold -------------------


def _match_label(fixture: Fixture, team, opp) -> str:
    hg, ag = fixture.home_goals_90, fixture.away_goals_90
    gf, ga = (hg, ag) if team.id == fixture.home_id else (ag, hg)
    verb = "won" if gf > ga else "lost" if gf < ga else "drew"
    extra = (
        " (won on pens)"
        if fixture.went_penalties
        else " (a.e.t.)" if fixture.went_extra_time else ""
    )
    opp_name = opp.name if opp else "?"
    return f"{fixture.stage.value} vs {opp_name}, {verb} {gf}-{ga} at 90'{extra}"


def _postprocess(conn: sqlite3.Connection, fixture: Fixture, now: datetime) -> None:
    """Write each team's post-match recap (idempotent) and fold it into the dossier
    exactly once (guarded by the dossier_update marker)."""
    home = db.get_team(conn, fixture.home_id) if fixture.home_id else None
    away = db.get_team(conn, fixture.away_id) if fixture.away_id else None
    played_on = fixture.kickoff.date().isoformat()
    for team, opp in ((home, away), (away, home)):
        if team is None:
            continue
        recap = intelligence.build_post_match_report(
            conn,
            team,
            match_label=_match_label(fixture, team, opp),
            played_on=played_on,
            fixture_id=fixture.id,
        )
        if not db.dossier_folded(conn, fixture.id, team.id):
            intelligence.update_dossier_after_match(conn, team, recap)
            db.mark_dossier_folded(conn, fixture.id, team.id, now.isoformat())


# ---- The tick ------------------------------------------------------------


def _new_summary() -> dict:
    return {
        "results": 0,
        "settled": 0,
        "postprocessed": 0,
        "resolved": 0,
        "decayed": 0,
        "briefed": 0,
        "predicted": 0,
        "errors": [],
    }


def tick(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict:
    """Run one pipeline pass. Returns a counts + errors summary. Per-item failures are
    caught so one bad fixture never aborts the tick."""
    now = now or _now()
    fixtures = db.list_fixtures(conn)
    s = _new_summary()

    # 1. Ingest results for matches that should be finished.
    for f in due_for_result(fixtures, now):
        try:
            if results.ingest_result(conn, f.id) is not None:
                s["results"] += 1
        except Exception as e:  # noqa: BLE001 - keep the tick alive
            s["errors"].append(f"result {f.id}: {e}")
    fixtures = db.list_fixtures(conn)  # refresh: some are now resolved

    # 2. Settle bets on resolved fixtures.
    for f in due_for_settle(conn, fixtures):
        try:
            settlement.settle_fixture(conn, f.id)
            s["settled"] += 1
        except Exception as e:  # noqa: BLE001
            s["errors"].append(f"settle {f.id}: {e}")

    # 3. Post-match recap + dossier fold (feeds future briefings — must precede brief).
    for f in due_for_postprocess(conn, fixtures):
        try:
            _postprocess(conn, f, now)
            s["postprocessed"] += 1
        except Exception as e:  # noqa: BLE001
            s["errors"].append(f"postmatch {f.id}: {e}")

    # 4. Resolve knockout bracket ids from freshly-ingested results (must precede brief:
    #    a knockout fixture cannot be briefed until its sides are real team ids).
    try:
        counts = bracket.resolve_brackets(conn)
        s["resolved"] = counts["r32"] + counts["winner_loser"]
        if s["resolved"]:
            fixtures = db.list_fixtures(conn)  # refresh: newly-filled knockouts visible
    except Exception as e:  # noqa: BLE001
        s["errors"].append(f"bracket: {e}")

    # 5. Idle decay for fully-closed matchdays.
    for day in due_matchdays(conn, fixtures):
        try:
            settlement.apply_idle_decay(conn, day)
            s["decayed"] += 1
        except Exception as e:  # noqa: BLE001
            s["errors"].append(f"decay {day}: {e}")

    # 6. Build briefings for fixtures entering the pre-match window.
    for f in due_for_brief(conn, fixtures, now):
        try:
            intelligence.brief_fixture(conn, f.id)
            s["briefed"] += 1
        except Exception as e:  # noqa: BLE001
            s["errors"].append(f"brief {f.id}: {e}")

    # 7. Predict + bet for fixtures entering the bet window.
    for f in due_for_bet(conn, fixtures, now):
        try:
            predict.run_fixture(conn, f.id)
            s["predicted"] += 1
        except Exception as e:  # noqa: BLE001
            s["errors"].append(f"predict {f.id}: {e}")

    return s


# ---- CLI -----------------------------------------------------------------


def _cmd_tick(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    s = tick(conn)
    print(
        f"tick — results:{s['results']} settled:{s['settled']} "
        f"postmatch:{s['postprocessed']} resolved:{s['resolved']} "
        f"decay:{s['decayed']} briefed:{s['briefed']} predicted:{s['predicted']}"
    )
    for err in s["errors"]:
        print(f"  ERROR {err}")


def _cmd_status(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    now = _now()
    fixtures = db.list_fixtures(conn)
    groups = {
        "result": due_for_result(fixtures, now),
        "settle": due_for_settle(conn, fixtures),
        "postmatch": due_for_postprocess(conn, fixtures),
        "brief": due_for_brief(conn, fixtures, now),
        "bet": due_for_bet(conn, fixtures, now),
    }
    print(f"Orchestrator status @ {now.isoformat()} (UTC)")
    for phase, fs in groups.items():
        ids = ", ".join(str(f.id) for f in fs) or "—"
        print(f"  {phase:<10} {len(fs):>3}  [{ids}]")
    days = due_matchdays(conn, fixtures)
    print(f"  {'decay':<10} {len(days):>3}  [{', '.join(days) or '—'}]")


def main() -> None:
    parser = argparse.ArgumentParser(prog="worldcup_agents.orchestrate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tick", help="run one pipeline pass (for the systemd timer)")
    t.set_defaults(func=_cmd_tick)

    st = sub.add_parser("status", help="show what is due now without acting")
    st.set_defaults(func=_cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
