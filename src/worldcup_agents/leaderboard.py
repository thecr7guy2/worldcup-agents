"""The two leaderboards (DESIGN §6) — read-only views over competition state.

    Bankroll (primary)  — prediction + risk management: "best gambler?"
    Accuracy (secondary) — raw correctness, stakes ignored: "best predictor?"

A model can pick winners well but bet timidly (high accuracy, low bankroll) or
vice versa — the two boards together are the experiment's headline result.

Accuracy is graded off the PREDICTION (Step 1), never the bet: correct ⟺
`prediction.winner == fixture.result_90()`, counted only over fixtures whose
90-minute result is known. The 1X2-on-90' convention carries through here too — a
predicted home win in a 1-1 match settled on penalties is simply WRONG.
"""

from __future__ import annotations

import argparse
import sqlite3

from . import db
from .config import POINTS_CORRECT_OUTCOME, POINTS_CORRECT_SCORE
from .models import Competitor, Fixture, MatchStatus


def bankroll_standings(conn: sqlite3.Connection) -> list[Competitor]:
    """Competitors ordered by bankroll (descending) — the primary leaderboard."""
    return db.list_competitors(conn)


def accuracy_standings(conn: sqlite3.Connection) -> list[dict]:
    """Per-model weighted accuracy over fixtures with a known 90' result.

    Points (DESIGN §6, graded off the PREDICT step, stakes ignored): a correct exact
    90' scoreline scores POINTS_CORRECT_SCORE; a correct outcome with the wrong score
    scores POINTS_CORRECT_OUTCOME; a wrong outcome scores 0. Returns dicts
    {model, points, exact, outcomes, total, hit_rate}, ordered by points then exact
    then outcomes. Predictions on unfinished/postponed fixtures are excluded.
    """
    finished: dict[int, Fixture] = {
        fx.id: fx
        for fx in db.list_fixtures(conn)
        if fx.status == MatchStatus.FINISHED and fx.result_90() is not None
    }
    tally: dict[str, dict] = {}
    for p in db.list_predictions(conn):
        fx = finished.get(p.fixture_id)
        if fx is None:
            continue  # no settled result for this fixture yet
        t = tally.setdefault(
            p.model_name, {"points": 0, "exact": 0, "outcomes": 0, "total": 0}
        )
        t["total"] += 1
        exact = (
            p.has_score
            and p.pred_home_goals == fx.home_goals_90
            and p.pred_away_goals == fx.away_goals_90
        )
        if exact:
            t["exact"] += 1
            t["outcomes"] += 1
            t["points"] += POINTS_CORRECT_SCORE
        elif p.winner == fx.result_90():
            t["outcomes"] += 1
            t["points"] += POINTS_CORRECT_OUTCOME

    rows = [
        {
            "model": m,
            "points": t["points"],
            "exact": t["exact"],
            "outcomes": t["outcomes"],
            "total": t["total"],
            "hit_rate": (t["outcomes"] / t["total"]) if t["total"] else 0.0,
        }
        for m, t in tally.items()
    ]
    rows.sort(key=lambda r: (r["points"], r["exact"], r["outcomes"]), reverse=True)
    return rows


# ---- CLI -----------------------------------------------------------------


def _print_bankroll(conn: sqlite3.Connection) -> None:
    print("Bankroll leaderboard — best gambler")
    print(f"{'#':<3}{'model':<18}{'bankroll':>16}{'lives':>7}{'status':>9}")
    for i, c in enumerate(bankroll_standings(conn), start=1):
        status = "active" if c.active else "OUT"
        print(
            f"{i:<3}{c.model_name:<18}{c.bankroll:>16,.0f}{c.lives_used:>7}{status:>9}"
        )


def _print_accuracy(conn: sqlite3.Connection) -> None:
    rows = accuracy_standings(conn)
    print("Accuracy leaderboard — best predictor (exact score = 2pts, outcome = 1pt)")
    if not rows:
        print("(no graded predictions yet)")
        return
    print(
        f"{'#':<3}{'model':<18}{'points':>7}{'exact':>7}{'outcome':>9}"
        f"{'total':>7}{'hit rate':>10}"
    )
    for i, r in enumerate(rows, start=1):
        print(
            f"{i:<3}{r['model']:<18}{r['points']:>7}{r['exact']:>7}{r['outcomes']:>9}"
            f"{r['total']:>7}{r['hit_rate']:>9.1%}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="worldcup_agents.leaderboard")
    parser.add_argument(
        "which",
        nargs="?",
        choices=("both", "bankroll", "accuracy"),
        default="both",
        help="which leaderboard to print (default: both)",
    )
    args = parser.parse_args()

    conn = db.connect()
    db.init_db(conn)
    if args.which in ("both", "bankroll"):
        _print_bankroll(conn)
    if args.which == "both":
        print()
    if args.which in ("both", "accuracy"):
        _print_accuracy(conn)


if __name__ == "__main__":
    main()
