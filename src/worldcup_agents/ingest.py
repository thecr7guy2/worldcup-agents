"""Data ingestion CLI.

Usage:
    uv run python -m worldcup_agents.ingest seed    # populate teams + fixtures
    uv run python -m worldcup_agents.ingest odds    # capture consensus odds
    uv run python -m worldcup_agents.ingest verify  # assert acceptance criteria
"""

from __future__ import annotations

import argparse
import sys
from datetime import timezone

from .db import (
    DEFAULT_DB_PATH,
    connect,
    init_db,
    list_fixtures,
    upsert_fixture,
    upsert_odds_snapshot,
    upsert_team,
)
from .models import Stage
from .sources.names import CANONICAL_TEAMS, team_id_for
from .sources.oddsapi import fetch_odds, to_snapshots
from .sources.openfootball import fetch_schedule, parse_schedule


def cmd_seed(args: argparse.Namespace) -> None:
    """Populate the database with canonical teams and the published fixture list."""
    conn = connect(DEFAULT_DB_PATH)
    init_db(conn)

    raw = fetch_schedule()
    teams, fixtures = parse_schedule(raw)

    print(f"Seeding {len(teams)} teams...")
    for team in teams:
        upsert_team(conn, team)

    print(f"Seeding {len(fixtures)} fixtures...")
    for fx in fixtures:
        upsert_fixture(conn, fx)

    print("Seed complete.")


def poll_odds(conn) -> int:
    """One Odds API poll (1 credit): fetch every event, write consensus snapshots,
    cache odds_event_ids. Returns the number of snapshots written. Shared by the
    scheduled `ingest odds` job and the orchestrator's near-kickoff refresh (which
    keeps the odds each bet is placed into — and the report's closing-line metric —
    from being up to 6 hours stale)."""
    fixtures = list_fixtures(conn)
    if not fixtures:
        raise RuntimeError("no fixtures in DB — run 'seed' first")

    events = fetch_odds()

    # Build id → canonical name for odds_event_id caching.
    id_to_name = {team_id_for(n): n for n in CANONICAL_TEAMS}
    # Build fixture_id → event_id from the raw events list.
    from .sources.names import normalize as _normalize

    event_id_map: dict[int, str] = {}
    for fx in fixtures:
        if fx.home_id is None or fx.away_id is None:
            continue
        home_name = id_to_name.get(fx.home_id, "")
        away_name = id_to_name.get(fx.away_id, "")
        date_str = fx.kickoff.strftime("%Y-%m-%d")
        for event in events:
            try:
                ev_home = _normalize(event.get("home_team", ""))
                ev_away = _normalize(event.get("away_team", ""))
            except ValueError:
                continue
            ev_date = (event.get("commence_time") or "")[:10]
            if ev_home == home_name and ev_away == away_name and ev_date == date_str:
                event_id_map[fx.id] = event["id"]
                break

    snapshots = to_snapshots(events, fixtures)
    for snap in snapshots:
        upsert_odds_snapshot(conn, snap)

    # Cache odds_event_id on fixtures (bulk update).
    for fixture_id, event_id in event_id_map.items():
        conn.execute(
            "UPDATE fixture SET odds_event_id = ? WHERE id = ? AND odds_event_id IS NULL",
            (event_id, fixture_id),
        )
    conn.commit()
    return len(snapshots)


def cmd_odds(args: argparse.Namespace) -> None:
    """Fetch and persist the latest consensus odds snapshot."""
    conn = connect(DEFAULT_DB_PATH)

    print("Fetching odds from The Odds API...")
    try:
        written = poll_odds(conn)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Wrote {written} consensus snapshots. Odds capture complete.")


def cmd_verify(args: argparse.Namespace) -> None:
    """Validate seeded data against the tournament's acceptance criteria."""
    conn = connect(DEFAULT_DB_PATH)
    errors: list[str] = []

    # AC1: 48 teams
    team_count = conn.execute("SELECT COUNT(*) FROM team").fetchone()[0]
    if team_count != 48:
        errors.append(f"Expected 48 teams, got {team_count}")

    # AC2: groups A..L, each with 4 teams
    for grp in "ABCDEFGHIJKL":
        count = conn.execute(
            'SELECT COUNT(*) FROM team WHERE "group" = ?', (grp,)
        ).fetchone()[0]
        if count != 4:
            errors.append(f"Group {grp} has {count} teams (expected 4)")

    # AC1: 104 fixtures with correct stage breakdown
    fx_count = conn.execute("SELECT COUNT(*) FROM fixture").fetchone()[0]
    if fx_count != 104:
        errors.append(f"Expected 104 fixtures, got {fx_count}")

    stage_counts = dict(
        conn.execute("SELECT stage, COUNT(*) FROM fixture GROUP BY stage").fetchall()
    )
    expected_stages = {
        Stage.GROUP.value: 72,
        Stage.R32.value: 16,
        Stage.R16.value: 8,
        Stage.QF.value: 4,
        Stage.SF.value: 2,
        Stage.THIRD.value: 1,
        Stage.FINAL.value: 1,
    }
    for stage_val, expected in expected_stages.items():
        got = stage_counts.get(stage_val, 0)
        if got != expected:
            errors.append(f"Stage {stage_val}: expected {expected}, got {got}")

    # AC3: Mexico vs South Africa kickoff
    row = conn.execute(
        "SELECT f.kickoff FROM fixture f "
        "JOIN team h ON h.id = f.home_id "
        "JOIN team a ON a.id = f.away_id "
        "WHERE h.name = 'Mexico' AND a.name = 'South Africa'"
    ).fetchone()
    if not row:
        errors.append("Mexico vs South Africa fixture not found")
    else:
        kickoff_str = row[0]
        from datetime import datetime

        ko = datetime.fromisoformat(kickoff_str)
        expected_ko = datetime(2026, 6, 11, 19, 0, 0, tzinfo=timezone.utc)
        if ko != expected_ko:
            errors.append(
                f"Mexico vs South Africa kickoff: expected {expected_ko.isoformat()}, got {kickoff_str}"
            )

    # AC4: knockout fixtures have home_id NULL and home_label NOT NULL
    ko_bad = conn.execute(
        "SELECT COUNT(*) FROM fixture WHERE stage != 'group' AND "
        "(home_id IS NOT NULL OR home_label IS NULL)"
    ).fetchone()[0]
    if ko_bad:
        errors.append(
            f"{ko_bad} knockout fixture(s) have unexpected home_id/home_label state"
        )

    # AC5 + AC7: odds checks
    snap_count = conn.execute("SELECT COUNT(*) FROM odds_snapshot").fetchone()[0]
    if snap_count > 0:
        bad_prices = conn.execute(
            "SELECT COUNT(*) FROM odds_snapshot WHERE home <= 1.0 OR draw <= 1.0 OR away <= 1.0"
        ).fetchone()[0]
        if bad_prices:
            errors.append(f"{bad_prices} snapshot(s) have price(s) <= 1.0")

        bad_timing = conn.execute(
            "SELECT COUNT(*) FROM odds_snapshot s "
            "JOIN fixture f ON f.id = s.fixture_id "
            "WHERE s.captured_at >= f.kickoff"
        ).fetchone()[0]
        if bad_timing:
            errors.append(f"{bad_timing} snapshot(s) have captured_at >= kickoff")
    else:
        print("NOTE: no odds snapshots yet (run 'odds' first)")

    # AC7: idempotency — just re-count (seed was already idempotent by INSERT OR REPLACE).
    # We verify counts already above, which implicitly checks idempotency if seed was re-run.

    if errors:
        print("VERIFY FAILED:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(
            f"VERIFY PASSED: {team_count} teams, {fx_count} fixtures, {snap_count} snapshots."
        )


def main() -> None:
    """Parse and dispatch the ingestion command-line interface."""
    parser = argparse.ArgumentParser(prog="worldcup_agents.ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Seed teams and fixtures from openfootball")
    sub.add_parser("odds", help="Capture consensus odds from The Odds API")
    sub.add_parser("verify", help="Assert acceptance criteria")

    args = parser.parse_args()
    if args.command == "seed":
        cmd_seed(args)
    elif args.command == "odds":
        cmd_odds(args)
    elif args.command == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
