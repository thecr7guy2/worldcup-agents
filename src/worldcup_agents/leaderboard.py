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
from .models import Competitor, MatchStatus


def bankroll_standings(conn: sqlite3.Connection) -> list[Competitor]:
    """Competitors ordered by bankroll (descending) — the primary leaderboard."""
    return db.list_competitors(conn)


def accuracy_standings(conn: sqlite3.Connection) -> list[dict]:
    """Per-model correctness over fixtures with a known 90' result.

    Returns dicts {model, correct, total, hit_rate}, ordered by correct count then
    hit-rate. Predictions on unfinished/postponed fixtures are excluded.
    """
    results = {
        fx.id: fx.result_90()
        for fx in db.list_fixtures(conn)
        if fx.status == MatchStatus.FINISHED and fx.result_90() is not None
    }
    tally: dict[str, list[int]] = {}  # model -> [correct, total]
    for p in db.list_predictions(conn):
        outcome = results.get(p.fixture_id)
        if outcome is None:
            continue  # no settled result for this fixture yet
        t = tally.setdefault(p.model_name, [0, 0])
        t[1] += 1
        if p.winner == outcome:
            t[0] += 1

    rows = [
        {
            "model": m,
            "correct": c,
            "total": n,
            "hit_rate": (c / n) if n else 0.0,
        }
        for m, (c, n) in tally.items()
    ]
    rows.sort(key=lambda r: (r["correct"], r["hit_rate"]), reverse=True)
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
    print("Accuracy leaderboard — best predictor")
    if not rows:
        print("(no graded predictions yet)")
        return
    print(f"{'#':<3}{'model':<18}{'correct':>9}{'total':>7}{'hit rate':>10}")
    for i, r in enumerate(rows, start=1):
        print(
            f"{i:<3}{r['model']:<18}{r['correct']:>9}{r['total']:>7}"
            f"{r['hit_rate']:>9.1%}"
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
