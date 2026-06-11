"""REAL multi-fixture dry run — two simultaneous matches against the live models.

    uv run python scripts/dry_run_multi.py            # all competitors, 2 fixtures
    uv run python scripts/dry_run_multi.py --models 2 # cheaper: briefing + 2 models

Like dry_run.py this spends real OpenRouter credit (two briefings + web search, then every
model predicts & bets BOTH matches). Its extra purpose: validate the new concurrent-exposure
path before matchday — i.e. that when a model bets the SECOND of two still-unsettled matches,
the live bet prompt carries the "$X already staked / free ≈ $Y" note and the model still
returns clean JSON. Bets run fixture-major (all models match 1, then all models match 2),
exactly like the orchestrator's due_for_bet loop, so each model's match-1 stake is open when
it sizes match 2.
"""

from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worldcup_agents import db, intelligence, predict
from worldcup_agents.config import PREDICTION_MODELS, openrouter_ready
from worldcup_agents.models import Fixture, MatchStatus, OddsSnapshot, Stage, Team
from worldcup_agents.sources.names import team_id_for

# Two synthetic-but-real-team fixtures sharing a group's final round (ids never collide with
# real 1..104 / surrogate ids). Strong sides → rich briefings.
MATCHES = [
    (9001, "Brazil", "Morocco", {"home": 1.65, "draw": 3.80, "away": 5.50}),
    (9002, "Argentina", "Croatia", {"home": 1.80, "draw": 3.50, "away": 4.60}),
]
GROUP = "X"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed(path: Path) -> tuple:
    conn = db.connect(path)
    db.init_db(conn)
    fixtures = []
    for fid, home, away, odds in MATCHES:
        hid, aid = team_id_for(home), team_id_for(away)
        db.upsert_team(conn, Team(id=hid, name=home, group=GROUP))
        db.upsert_team(conn, Team(id=aid, name=away, group=GROUP))
        fx = Fixture(id=fid, stage=Stage.GROUP, group=GROUP,
                     kickoff=_now() + timedelta(hours=6), venue="Dry-Run Stadium",
                     home_id=hid, away_id=aid, status=MatchStatus.SCHEDULED)
        db.upsert_fixture(conn, fx)
        db.upsert_odds_snapshot(conn, OddsSnapshot(fixture_id=fid, captured_at=_now(),
            bookmaker="consensus", home=odds["home"], draw=odds["draw"], away=odds["away"]))
        fixtures.append(fx)
    return conn, fixtures


def _telemetry(conn) -> None:
    rows = db.usage_by_model(conn)
    print(f"\n{'model':<18}{'calls':>7}{'tokens':>10}{'cost (USD)':>14}")
    total = 0.0
    for r in rows:
        cost = r["cost_usd"] or 0.0
        total += cost
        print(f"{r['model_name']:<18}{r['calls']:>7}{(r['tokens'] or 0):>10,}{cost:>14.4f}")
    print(f"{'TOTAL':<18}{'':>7}{'':>10}{total:>14.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="dry_run_multi")
    ap.add_argument("--models", type=int, default=0,
                    help="cap competitors (0 = all; e.g. 2 for a cheaper run)")
    args = ap.parse_args()
    if not openrouter_ready():
        raise SystemExit("OPENROUTER_API_KEY is not set — fill .env before the dry run.")

    models = PREDICTION_MODELS[: args.models] if args.models else PREDICTION_MODELS
    conn, fixtures = _seed(Path(tempfile.mkdtemp(prefix="wc_multidry_")) / "multi.db")

    print("=" * 80)
    print("REAL MULTI-FIXTURE DRY RUN — two simultaneous matches")
    for fx in fixtures:
        h, a = db.get_team(conn, fx.home_id).name, db.get_team(conn, fx.away_id).name
        print(f"  · {fx.id}  {h} vs {a}")
    print(f"  competitors: {len(models)} ({', '.join(m.name for m in models)})")
    print("  NOTE: spends real OpenRouter credit (2 briefings + web search + reasoning).")
    print("=" * 80)

    # --- Brief both fixtures up front (each: dossiers + pre-match reports + late update) ---
    briefs, lates = {}, {}
    for fx in fixtures:
        print(f"\n[brief] fixture {fx.id} …")
        try:
            briefs[fx.id] = intelligence.brief_fixture(conn, fx.id)
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ briefing FAILED: {type(e).__name__}: {e}")
            _telemetry(conn)
            raise SystemExit(1)
        try:
            lates[fx.id] = intelligence.build_late_update(conn, fx, cutoff=_now()).content
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️  late update unavailable ({type(e).__name__}) — continuing")
            lates[fx.id] = None

    # --- Bet phase, FIXTURE-MAJOR (match 1 for everyone, then match 2) ---
    failures: list[tuple[str, str]] = []
    for fx in fixtures:  # order matters: match-1 stakes must be open when match 2 is sized
        h, a = db.get_team(conn, fx.home_id).name, db.get_team(conn, fx.away_id).name
        odds = db.consensus_odds(conn, fx.id)
        print(f"\n{'=' * 80}\nMATCH {fx.id}: {h} vs {a}\n{'=' * 80}")
        for model in models:
            comp = db.get_competitor(conn, model.name)
            bankroll = comp.bankroll if comp else 0.0
            # The note this model is ABOUT to receive (from its own already-open bets).
            ostake, ocount = db.open_exposure(conn, model.name)
            note = predict._exposure_note(bankroll, ostake, ocount)
            try:
                pred = predict.predict(conn, model, fx, briefs[fx.id], h, a,
                                       late_update=lates[fx.id])
                b = predict.bet(conn, model, fx, pred, odds, bankroll, h, a)
            except Exception as e:  # noqa: BLE001 — surface, never abort the others
                failures.append((f"{model.name}@{fx.id}", f"{type(e).__name__}: {e}"))
                print(f"  ✗ {model.name}: {type(e).__name__}: {e}")
                continue
            verdict = (f"{b.pick.value.upper()} ${b.stake:,.0f} @ {b.odds_at_bet}"
                       if not b.is_pass else "pass")
            probs = (f"  P(H/D/A) {pred.p_home:.0%}/{pred.p_draw:.0%}/{pred.p_away:.0%}"
                     if pred.has_distribution else "")
            print(f"\n  {model.name}  (bankroll ${bankroll:,.0f})")
            if note:
                print(f"    exposure note IN PROMPT → {note.strip()}")
            print(f"    predict: {pred.winner.value}{probs} · conf {pred.confidence:.2f}")
            print(f"    BET: {verdict}")
            if b.reasoning:
                print(f"    why: {b.reasoning[:240]}")

    print(f"\n{'=' * 80}")
    if failures:
        print(f"⚠️  {len(failures)} model/fixture call(s) FAILED:")
        for who, err in failures:
            print(f"   - {who}: {err}")
    else:
        print("✅ Every model produced valid predictions + bets on BOTH matches "
              "(exposure note parsed cleanly).")
    _telemetry(conn)


if __name__ == "__main__":
    main()
