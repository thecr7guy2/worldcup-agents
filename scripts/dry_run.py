"""End-to-end DRY RUN of the live prediction path — proves it before matchday.

    uv run python scripts/dry_run.py            # all competitors
    uv run python scripts/dry_run.py --models 1 # cheap smoke: briefing + 1 model

This is the one thing a forced `orchestrate tick` does NOT cover before June 11: the tick
no-ops until a real fixture enters its window, so the expensive briefing -> predict -> bet
path never actually executes against the live models until the opening match. This script
forces it now, in isolation, so a malformed-JSON / token-limit / bad-slug / web-search
problem surfaces with runway to fix it.

What it does (UNLIKE a tick, it spends real OpenRouter credit — a few cents to ~$1-2):
  - builds a THROWAWAY DB in a temp dir (never touches worldcup.db),
  - seeds ONE synthetic fixture (real teams, kickoff a few hours out) + a consensus-odds row,
  - runs intelligence.brief_fixture (dossiers + pre-match reports + context, via web search),
  - runs the exact run_fixture loop (each model: predict with odds hidden, then bet),
  - prints the briefing, every model's prediction + bet + full reasoning, per-model
    failures (surfaced, not fatal), and the cost/token telemetry.
"""

from __future__ import annotations

import argparse
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worldcup_agents import db, intelligence, predict
from worldcup_agents.config import PREDICTION_MODELS, openrouter_ready
from worldcup_agents.models import Fixture, MatchStatus, OddsSnapshot, Stage, Team
from worldcup_agents.sources.names import team_id_for

FIXTURE_ID = 9001  # synthetic, never collides with real ids (1..104 / surrogates ~200)
HOME, AWAY = (
    "Brazil",
    "Morocco",
)  # real teams w/ rich web presence → a meaningful briefing
ODDS = {
    "home": 1.65,
    "draw": 3.80,
    "away": 5.50,
}  # plausible consensus for this matchup


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed(path: Path) -> tuple[sqlite3.Connection, Fixture]:
    """Build an isolated DB with one briefable synthetic fixture + odds."""
    conn = db.connect(path)
    db.init_db(conn)  # schema + seeds the competitors at the starting bankroll
    hid, aid = team_id_for(HOME), team_id_for(AWAY)
    db.upsert_team(conn, Team(id=hid, name=HOME, group="C"))
    db.upsert_team(conn, Team(id=aid, name=AWAY, group="C"))
    fixture = Fixture(
        id=FIXTURE_ID,
        stage=Stage.GROUP,
        group="C",
        kickoff=_now() + timedelta(hours=6),  # future → briefing is temporally valid
        venue="Dry-Run Stadium",
        home_id=hid,
        away_id=aid,
        status=MatchStatus.SCHEDULED,
    )
    db.upsert_fixture(conn, fixture)
    db.upsert_odds_snapshot(
        conn,
        OddsSnapshot(
            fixture_id=FIXTURE_ID,
            captured_at=_now(),
            bookmaker="consensus",
            home=ODDS["home"],
            draw=ODDS["draw"],
            away=ODDS["away"],
        ),
    )
    return conn, fixture


def _print_table(results: list[tuple]) -> None:
    print(
        f"\n{'model':<18}{'predict':<8}{'score':>6}{'conf':>7}"
        f"{'bet':>7}{'stake':>12}{'odds':>7}"
    )
    for pred, b in results:
        pick = b.pick.value if b.pick else "pass"
        odds = f"{b.odds_at_bet:.2f}" if b.odds_at_bet else "—"
        score = (
            f"{pred.pred_home_goals}-{pred.pred_away_goals}" if pred.has_score else "—"
        )
        print(
            f"{pred.model_name:<18}{pred.winner.value:<8}{score:>6}{pred.confidence:>7.2f}"
            f"{pick:>7}{b.stake:>12,.0f}{odds:>7}"
        )


def _print_telemetry(conn: sqlite3.Connection) -> None:
    rows = db.usage_by_model(conn)
    print(f"\n{'model':<18}{'calls':>7}{'tokens':>10}{'cost (USD)':>14}")
    total = 0.0
    for r in rows:
        cost = r["cost_usd"] or 0.0
        total += cost
        print(
            f"{r['model_name']:<18}{r['calls']:>7}{(r['tokens'] or 0):>10,}{cost:>14.4f}"
        )
    print(f"{'TOTAL':<18}{'':>7}{'':>10}{total:>14.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="dry_run")
    parser.add_argument(
        "--models",
        type=int,
        default=0,
        help="cap competitors run (0 = all; e.g. 1 for a cheap smoke)",
    )
    args = parser.parse_args()

    if not openrouter_ready():
        raise SystemExit(
            "OPENROUTER_API_KEY is not set — fill .env before the dry run."
        )

    models = PREDICTION_MODELS[: args.models] if args.models else PREDICTION_MODELS
    db_path = Path(tempfile.mkdtemp(prefix="wc_dryrun_")) / "dry_run.db"
    conn, fixture = _seed(db_path)

    print("=" * 72)
    print(f"DRY RUN — {HOME} vs {AWAY} (synthetic fixture {FIXTURE_ID})")
    print(f"  throwaway DB: {db_path}")
    print(f"  competitors:  {len(models)} ({', '.join(m.name for m in models)})")
    print(
        f"  odds:         home {ODDS['home']} / draw {ODDS['draw']} / away {ODDS['away']}"
    )
    print("  NOTE: this spends real OpenRouter credit (web search + reasoning).")
    print("=" * 72)

    # --- Briefing (hard prerequisite: dossiers + pre-match reports + context) ---
    print("\n[1/2] Building briefing (intelligence agent, web search)…")
    try:
        briefing = intelligence.brief_fixture(conn, FIXTURE_ID)
    except Exception as e:  # noqa: BLE001 — the whole point is to surface failures
        print(f"\n❌ BRIEFING FAILED: {type(e).__name__}: {e}")
        print("   The prediction path can't run without a briefing — fix this first.")
        _print_telemetry(conn)
        raise SystemExit(1)
    print("\n" + "-" * 72 + "\n" + briefing.content + "\n" + "-" * 72)

    # --- Predict + bet (the exact run_fixture loop; per-model errors are surfaced) ---
    print(
        f"\n[2/2] Running {len(models)} competitor(s) — predict (odds hidden) then bet…"
    )
    odds = db.consensus_odds(conn, FIXTURE_ID)
    results: list[tuple] = []
    failures: list[tuple[str, str]] = []
    for model in models:
        try:
            comp = db.get_competitor(conn, model.name)
            bankroll = comp.bankroll if comp else 0.0
            pred = predict.predict(conn, model, fixture, briefing, HOME, AWAY)
            b = predict.bet(conn, model, fixture, pred, odds, bankroll, HOME, AWAY)
            results.append((pred, b))
            print(f"  ✓ {model.name}")
        except Exception as e:  # noqa: BLE001
            failures.append((model.name, f"{type(e).__name__}: {e}"))
            print(f"  ✗ {model.name}: {type(e).__name__}: {e}")

    if results:
        _print_table(results)
        print("\n" + predict.format_reasoning(FIXTURE_ID, HOME, AWAY, results))

    if failures:
        print(f"\n⚠️  {len(failures)} model(s) FAILED — investigate before June 11:")
        for name, err in failures:
            print(f"   - {name}: {err}")

    _print_telemetry(conn)

    ok = len(results)
    print(
        f"\n{'✅' if not failures else '⚠️ '} Dry run complete: "
        f"{ok}/{len(models)} competitor(s) produced a prediction + bet."
    )
    print(f"Inspect the throwaway DB with:  sqlite3 {db_path}")


if __name__ == "__main__":
    main()
