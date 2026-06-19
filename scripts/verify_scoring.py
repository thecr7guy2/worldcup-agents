"""Scoring regression test — synthetic, self-contained, no LLM/network.

    uv run python scripts/verify_scoring.py

Covers matchday portfolio/idle decay and the two leaderboards, including the DESIGN §7
carry-through: a predicted home win in a 1-1 match decided on penalties is graded WRONG
(draw on the 90-minute score).
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from worldcup_agents import db
from worldcup_agents.config import (
    IDLE_DECAY,
    MATCHDAY_SHORTFALL_PENALTY_FRACTION,
    MATCHDAY_TARGET_STAKE_FRACTION,
    POINTS_CORRECT_ADVANCE,
    POINTS_CORRECT_OUTCOME,
    POINTS_CORRECT_SCORE,
    STARTING_BANKROLL,
)
from worldcup_agents.leaderboard import accuracy_standings, bankroll_standings
from worldcup_agents.models import (
    Bet,
    Fixture,
    Outcome,
    Prediction,
    Stage,
    Team,
)
from worldcup_agents.settlement import apply_idle_decay, record_result

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
DAY = "2026-06-11"


def _fixture(conn, fid, **kw):
    """Insert a fixture with configurable result fields for scoring checks."""
    db.upsert_fixture(
        conn,
        Fixture(
            id=fid,
            stage=Stage.GROUP,
            group="A",
            kickoff=datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc),
            home_id=1,
            away_id=2,
            **kw,
        ),
    )


def main() -> None:
    """Run leaderboard scoring and idle-decay checks."""
    tmp = Path(tempfile.mkdtemp()) / "wc_scoring.db"
    conn = db.connect(tmp)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Mexico", group="A"))
    db.upsert_team(conn, Team(id=2, name="South Africa", group="A"))

    comps = [c.model_name for c in db.list_competitors(conn)]
    passer, bettor, edge, out = comps[0], comps[1], comps[2], comps[3]

    # --- IDLE DECAY -------------------------------------------------------
    # One matchday with a single fixture; finish it so the day is "closed".
    _fixture(conn, 800)

    # bettor risks 200k on the matchday; edge risks its whole bankroll (idle <= 0).
    db.upsert_bet(
        conn,
        Bet(
            model_name=bettor,
            fixture_id=800,
            pick=Outcome.HOME,
            stake=200_000.0,
            odds_at_bet=2.0,
            created_at=NOW,
        ),
    )
    db.upsert_bet(
        conn,
        Bet(
            model_name=edge,
            fixture_id=800,
            pick=Outcome.HOME,
            stake=STARTING_BANKROLL,  # nothing idle
            odds_at_bet=2.0,
            created_at=NOW,
        ),
    )
    # `out` is eliminated and frozen — decay must skip it.
    conn.execute(
        "UPDATE competitor SET bankroll=?, active=0 WHERE model_name=?",
        (5_000.0, out),
    )
    conn.commit()

    # Close-guard: decay before the day is finished must raise.
    raised = False
    try:
        apply_idle_decay(conn, DAY)
    except ValueError:
        raised = True
    assert raised, "decay should refuse an unfinished matchday"

    record_result(conn, 800, 2, 1)  # finish the fixture → matchday closed
    apply_idle_decay(conn, DAY)

    # AC1 passer: portfolio shortfall penalty beats the tiny idle bleed.
    cp = db.get_competitor(conn, passer)
    passer_shortfall = STARTING_BANKROLL * MATCHDAY_TARGET_STAKE_FRACTION
    expected_passer = STARTING_BANKROLL - (
        passer_shortfall * MATCHDAY_SHORTFALL_PENALTY_FRACTION
    )
    assert abs(cp.bankroll - expected_passer) < 0.01, cp
    hist = db.list_bankroll_history(conn, passer)
    assert (
        len(hist) == 1
        and hist[0].reason == "portfolio_decay"
        and hist[0].fixture_id is None
    )
    assert cp.active is True and cp.lives_used == 0  # decay never busts

    # AC2 bettor met the matchday target, so only the tiny idle-cash floor applies;
    # edge has no idle cash and no shortfall → no change.
    cb = db.get_competitor(conn, bettor)
    expected = STARTING_BANKROLL - IDLE_DECAY * (STARTING_BANKROLL - 200_000.0)
    assert abs(cb.bankroll - expected) < 0.01, cb
    ce = db.get_competitor(conn, edge)
    assert (
        ce.bankroll == STARTING_BANKROLL and db.list_bankroll_history(conn, edge) == []
    )

    # AC3 eliminated competitor untouched.
    co = db.get_competitor(conn, out)
    assert co.bankroll == 5_000.0 and db.list_bankroll_history(conn, out) == []

    # AC4 idempotent: re-running the same matchday changes nothing.
    snap = {c.model_name: c.bankroll for c in db.list_competitors(conn)}
    assert apply_idle_decay(conn, DAY) == []
    assert {c.model_name: c.bankroll for c in db.list_competitors(conn)} == snap
    print(
        "portfolio decay (passer / target-met / no-idle / eliminated / idempotent / guard): PASS"
    )

    # --- LEADERBOARDS -----------------------------------------------------
    # Two finished fixtures with known results + an unfinished one (must be ignored).
    _fixture(conn, 801)
    record_result(conn, 801, 0, 0)  # result = DRAW
    _fixture(conn, 802)  # left SCHEDULED → excluded from accuracy

    # §7 knockout: 1-1 won on pens → settles/grades as DRAW.
    db.upsert_fixture(
        conn,
        Fixture(
            id=803,
            stage=Stage.R16,
            kickoff=datetime(2026, 7, 1, 19, 0, tzinfo=timezone.utc),
            home_id=1,
            away_id=2,
        ),
    )
    record_result(conn, 803, 1, 1, extra_time=True, penalties=True, advanced_id=1)

    def pred(model, fid, hg, ag, advances=None):
        """Insert one prediction used by the scoring scenarios."""
        winner = Outcome.HOME if hg > ag else Outcome.AWAY if hg < ag else Outcome.DRAW
        db.upsert_prediction(
            conn,
            Prediction(
                model_name=model,
                fixture_id=fid,
                winner=winner,
                pred_home_goals=hg,
                pred_away_goals=ag,
                predicted_advance=advances,
                confidence=0.6,
                reasoning="x",
                created_at=NOW,
            ),
        )

    # A finished knockout whose advancer is UNRESOLVED (advanced_id None) — advance must
    # not score even when predicted (gate test).
    db.upsert_fixture(
        conn,
        Fixture(
            id=804,
            stage=Stage.R16,
            kickoff=datetime(2026, 7, 2, 19, 0, tzinfo=timezone.utc),
            home_id=1,
            away_id=2,
        ),
    )
    record_result(conn, 804, 2, 1)  # decisive, but advanced_id left None

    # Results: 800=2-1 HOME (group), 801=0-0 DRAW (group), 803=1-1 pens DRAW (R16, HOME
    # advanced), 804=2-1 HOME (R16, advancer unresolved), 802=SCHEDULED (excluded).
    # passer — the showcase: 800 EXACT (+2); 801 outcome (+1); 803 called the 1-1 DRAW
    #   EXACT (+2) AND home advances CORRECT (+1).
    pred(passer, 800, 2, 1)
    pred(passer, 801, 1, 1)
    pred(passer, 803, 1, 1, advances=Outcome.HOME)
    # bettor: 800 wrong (+0); 801 EXACT (+2); 802 ignored (unfinished); 803 got the 90'
    #   WRONG (2-1, +0) but called the advancer right (+1) — advance is INDEPENDENT.
    pred(bettor, 800, 0, 2)
    pred(bettor, 801, 0, 0)
    pred(bettor, 802, 1, 0)
    pred(bettor, 803, 2, 1, advances=Outcome.HOME)
    # edge: 804 EXACT (+2) + predicts home advances, but 804's advancer is unresolved → +0.
    pred(edge, 804, 2, 1, advances=Outcome.HOME)

    acc = {r["model"]: r for r in accuracy_standings(conn)}
    # passer: 2 + 1 + (2 + 1) = 6 ; exact 2 (800,803) ; outcomes 3 ; advance 1 ; total 3
    assert acc[passer]["points"] == (
        2 * POINTS_CORRECT_SCORE + POINTS_CORRECT_OUTCOME + POINTS_CORRECT_ADVANCE
    ), acc[passer]
    assert acc[passer]["exact"] == 2 and acc[passer]["outcomes"] == 3
    assert acc[passer]["advance"] == 1 and acc[passer]["total"] == 3
    # bettor: 0 + 2 + 0 + 1 = 3 ; 802 excluded → total 3 ; advance 1 despite wrong 90'.
    assert acc[bettor]["points"] == POINTS_CORRECT_SCORE + POINTS_CORRECT_ADVANCE
    assert acc[bettor]["exact"] == 1 and acc[bettor]["outcomes"] == 1, acc[bettor]
    assert acc[bettor]["advance"] == 1 and acc[bettor]["total"] == 3
    # edge: exact on 804 but advancer unresolved (advanced_id None) → no advance point.
    assert acc[edge]["points"] == POINTS_CORRECT_SCORE and acc[edge]["advance"] == 0
    # ordering by points: passer (6) > bettor (3).
    order = [r["model"] for r in accuracy_standings(conn)]
    assert order.index(passer) < order.index(bettor)
    print("accuracy board (exact / outcome / KO advance: independence + gate): PASS")

    # --- Migration: an old-shape prediction table gains the score columns ---
    mtmp = Path(tempfile.mkdtemp()) / "old.db"
    raw = sqlite3.connect(mtmp)
    raw.execute(
        "CREATE TABLE prediction (model_name TEXT, fixture_id INTEGER, winner TEXT, "
        "confidence REAL, reasoning TEXT, created_at TEXT, "
        "PRIMARY KEY(model_name, fixture_id))"
    )
    raw.execute(
        "INSERT INTO prediction VALUES ('M', 1, 'home', 0.5, 'r', "
        "'2026-06-11T00:00:00+00:00')"
    )
    raw.commit()
    raw.close()
    mconn = db.connect(mtmp)
    db.init_db(mconn)  # must ALTER-add the columns, preserving the existing row
    cols = {r["name"] for r in mconn.execute("PRAGMA table_info(prediction)")}
    assert {"pred_home_goals", "pred_away_goals", "predicted_advance"} <= cols, cols
    saved = mconn.execute(
        "SELECT winner, pred_home_goals FROM prediction WHERE model_name='M'"
    ).fetchone()
    assert saved["winner"] == "home" and saved["pred_home_goals"] is None
    print("migration: old prediction table gains score columns, row preserved: PASS")

    # AC7 bankroll board ordered desc.
    board = bankroll_standings(conn)
    assert [c.bankroll for c in board] == sorted(
        (c.bankroll for c in board), reverse=True
    )
    print("bankroll board ordered by bankroll desc: PASS")

    print("\nALL ACCEPTANCE CRITERIA PASS")


if __name__ == "__main__":
    main()
