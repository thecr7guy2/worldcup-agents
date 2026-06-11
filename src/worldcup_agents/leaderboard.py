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
from .config import (
    POINTS_CORRECT_ADVANCE,
    POINTS_CORRECT_OUTCOME,
    POINTS_CORRECT_SCORE,
)
from .models import Competitor, Fixture, MatchStatus, Outcome


def bankroll_standings(conn: sqlite3.Connection) -> list[Competitor]:
    """Competitors ordered by bankroll (descending) — the primary leaderboard."""
    return db.list_competitors(conn)


def accuracy_standings(
    conn: sqlite3.Connection, *, include_human: bool = False
) -> list[dict]:
    """Per-model weighted accuracy over fixtures with a known 90' result.

    Points (DESIGN §6, graded off the PREDICT step, stakes ignored): a correct exact
    90' scoreline scores POINTS_CORRECT_SCORE; a correct outcome with the wrong score
    scores POINTS_CORRECT_OUTCOME; a wrong outcome scores 0. On knockouts, correctly
    calling who PROGRESSES (ET/penalties) adds POINTS_CORRECT_ADVANCE — independent of
    the 90' points (so a correct 1-1 draw + correct advancer scores both). Returns
    {model, points, exact, outcomes, advance, total, hit_rate}, ordered by points then
    exact then advance. Predictions on unfinished/postponed fixtures are excluded.
    """
    finished: dict[int, Fixture] = {
        fx.id: fx
        for fx in db.list_fixtures(conn)
        if fx.status == MatchStatus.FINISHED and fx.result_90() is not None
    }
    # The secret Human Challenger predicts too, but stays off the public accuracy board
    # until revealed; his rows are still graded when include_human=True (his private view).
    hidden = set() if include_human else db.human_names(conn)
    tally: dict[str, dict] = {}
    for p in db.list_predictions(conn):
        if p.model_name in hidden:
            continue
        fx = finished.get(p.fixture_id)
        if fx is None:
            continue  # no settled result for this fixture yet
        t = tally.setdefault(
            p.model_name,
            {"points": 0, "exact": 0, "outcomes": 0, "advance": 0, "total": 0},
        )
        t["total"] += 1
        # Outcome is graded off `winner` (argmax of the 1X2 distribution); the exact scoreline
        # is graded off the separate `pred_*_goals` modal score. They can disagree (winner=home
        # while modal score is 1-1). To keep points unambiguous, the exact-score bonus is only
        # awarded when the OUTCOME is also correct — i.e. the forecast is internally coherent
        # (a 1-1 modal score earns the exact bonus only if the model's winner was DRAW). A
        # correct outcome with the wrong score scores the outcome point; a wrong outcome scores
        # nothing, even if the modal score happened to match.
        outcome_correct = p.winner == fx.result_90()
        exact = (
            outcome_correct
            and p.has_score
            and p.pred_home_goals == fx.home_goals_90
            and p.pred_away_goals == fx.away_goals_90
        )
        if outcome_correct:
            t["outcomes"] += 1
        if exact:
            t["exact"] += 1
            t["points"] += POINTS_CORRECT_SCORE  # supersedes the outcome point
        elif outcome_correct:
            t["points"] += POINTS_CORRECT_OUTCOME

        # Knockout-only: who advanced (penalties count). Independent of the 90' points;
        # gated on a resolved advancer, so group fixtures (advanced_id None) never score.
        if fx.advanced_id is not None and p.predicted_advance is not None:
            advanced_side = (
                Outcome.HOME if fx.advanced_id == fx.home_id else Outcome.AWAY
            )
            if p.predicted_advance == advanced_side:
                t["advance"] += 1
                t["points"] += POINTS_CORRECT_ADVANCE

    rows = [
        {
            "model": m,
            "points": t["points"],
            "exact": t["exact"],
            "outcomes": t["outcomes"],
            "advance": t["advance"],
            "total": t["total"],
            "hit_rate": (t["outcomes"] / t["total"]) if t["total"] else 0.0,
        }
        for m, t in tally.items()
    ]
    rows.sort(key=lambda r: (r["points"], r["exact"], r["advance"]), reverse=True)
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
    print(
        "Accuracy leaderboard — best predictor "
        "(exact score = 2pts, outcome = 1pt, KO advancer = +1)"
    )
    if not rows:
        print("(no graded predictions yet)")
        return
    print(
        f"{'#':<3}{'model':<18}{'points':>7}{'exact':>7}{'outcome':>9}{'adv':>5}"
        f"{'total':>7}{'hit rate':>10}"
    )
    for i, r in enumerate(rows, start=1):
        print(
            f"{i:<3}{r['model']:<18}{r['points']:>7}{r['exact']:>7}{r['outcomes']:>9}"
            f"{r['advance']:>5}{r['total']:>7}{r['hit_rate']:>9.1%}"
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
