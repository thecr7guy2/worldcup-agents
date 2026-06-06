"""Settlement regression test — synthetic, self-contained, no LLM/network.

    uv run python scripts/verify_settlement.py

Builds a throwaway DB in a temp file, hand-writes bets covering every settlement
case, and asserts the grading + bankroll + bust/re-buy math (todo-settlement §3).
Guards the load-bearing DESIGN §7 rule: a knockout 1-1 won on penalties settles as
a DRAW on the 90-minute score, so a bet on either team LOSES.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from worldcup_agents import db
from worldcup_agents.config import BANKRUPT_FLOOR, REBUY_AMOUNT, STARTING_BANKROLL
from worldcup_agents.models import (
    Bet,
    BetResult,
    Fixture,
    Outcome,
    Stage,
    Team,
)
from worldcup_agents.settlement import record_result, settle_fixture

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


def _bet(conn, model, fid, pick, stake, odds):
    db.upsert_bet(
        conn,
        Bet(
            model_name=model,
            fixture_id=fid,
            pick=pick,
            stake=stake,
            odds_at_bet=odds,
            created_at=NOW,
        ),
    )


def _fixture(conn, fid, stage, **kw):
    db.upsert_fixture(
        conn,
        Fixture(
            id=fid,
            stage=stage,
            kickoff=datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc),
            home_id=1,
            away_id=2,
            **kw,
        ),
    )


def main() -> None:
    tmp = Path(tempfile.mkdtemp()) / "wc_settle_regression.db"
    conn = db.connect(tmp)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Mexico", group="A"))
    db.upsert_team(conn, Team(id=2, name="South Africa", group="A"))

    comps = [c.model_name for c in db.list_competitors(conn)]
    winner, loser, passer, buster = comps[0], comps[1], comps[2], comps[3]

    # --- Group fixture: WIN / LOSS / PASS / BUST→REBUY in one settlement ---
    _fixture(conn, 900, Stage.GROUP, group="A")
    _bet(conn, winner, 900, Outcome.HOME, 100_000.0, 2.0)
    _bet(conn, loser, 900, Outcome.AWAY, 100_000.0, 3.0)
    db.upsert_bet(
        conn,
        Bet(model_name=passer, fixture_id=900, pick=None, stake=0.0, created_at=NOW),
    )
    # Just above floor: 12k, 25% cap = 3k, lose → 9k <= 10k floor → re-buy.
    buster_start = BANKRUPT_FLOOR + 2_000.0
    conn.execute(
        "UPDATE competitor SET bankroll = ? WHERE model_name = ?",
        (buster_start, buster),
    )
    conn.commit()
    _bet(conn, buster, 900, Outcome.AWAY, buster_start * 0.25, 2.0)

    record_result(conn, 900, 2, 1, advanced_id=1)
    assert db.get_fixture(conn, 900).result_90() is Outcome.HOME
    settle_fixture(conn, 900)

    sw = db.get_settlement(conn, winner, 900)
    assert sw.result is BetResult.WIN and sw.pnl == 100_000.0 and sw.payout == 200_000.0
    assert db.get_competitor(conn, winner).bankroll == STARTING_BANKROLL + 100_000.0

    sl = db.get_settlement(conn, loser, 900)
    assert sl.result is BetResult.LOSS and sl.pnl == -100_000.0 and sl.payout == 0.0
    assert db.get_competitor(conn, loser).bankroll == STARTING_BANKROLL - 100_000.0

    sp = db.get_settlement(conn, passer, 900)
    assert sp.result is BetResult.PASS and sp.pnl == 0.0
    assert db.get_competitor(conn, passer).bankroll == STARTING_BANKROLL
    assert db.list_bankroll_history(conn, passer) == []

    cb = db.get_competitor(conn, buster)
    assert cb.bankroll == REBUY_AMOUNT and cb.lives_used == 1 and cb.active is True
    assert [e.reason for e in db.list_bankroll_history(conn, buster)] == [
        "bet_settled",
        "rebuy",
    ]
    print("group-stage WIN/LOSS/PASS/BUST→REBUY: PASS")

    # --- Idempotent + atomic re-run ---
    snap = {c.model_name: c.bankroll for c in db.list_competitors(conn)}
    hist = {m: len(db.list_bankroll_history(conn, m)) for m in comps}
    settle_fixture(conn, 900)
    assert {c.model_name: c.bankroll for c in db.list_competitors(conn)} == snap
    assert {m: len(db.list_bankroll_history(conn, m)) for m in comps} == hist
    print("idempotent re-settle (no further bankroll/ledger change): PASS")

    # --- Second bust with no life left → elimination, bankroll frozen ---
    conn.execute(
        "UPDATE competitor SET bankroll=?, lives_used=1, active=1 WHERE model_name=?",
        (buster_start, buster),
    )
    conn.commit()
    _fixture(conn, 903, Stage.GROUP, group="A")
    _bet(conn, buster, 903, Outcome.AWAY, buster_start * 0.25, 2.0)
    record_result(conn, 903, 2, 0)  # home win → away bet loses
    settle_fixture(conn, 903)
    ce = db.get_competitor(conn, buster)
    assert (
        ce.active is False and ce.lives_used == 1 and abs(ce.bankroll - 9_000.0) < 1e-6
    )
    print("second bust, no life → eliminated (active=False), bankroll frozen: PASS")

    # --- VOID: postponed fixture refunds the stake, no bankroll change ---
    _fixture(conn, 901, Stage.GROUP, group="A")
    before = db.get_competitor(conn, winner).bankroll
    _bet(conn, winner, 901, Outcome.HOME, 50_000.0, 1.8)
    record_result(conn, 901, None, None, postponed=True)
    settle_fixture(conn, 901)
    sv = db.get_settlement(conn, winner, 901)
    assert sv.result is BetResult.VOID and sv.pnl == 0.0 and sv.payout == 50_000.0
    assert db.get_competitor(conn, winner).bankroll == before
    print("postponed → VOID (stake refunded, no bankroll change): PASS")

    # --- DESIGN §7: knockout 1-1 won on penalties settles as a DRAW ---
    _fixture(conn, 902, Stage.R16)
    before = db.get_competitor(conn, loser).bankroll
    _bet(conn, loser, 902, Outcome.HOME, 10_000.0, 2.5)
    record_result(conn, 902, 1, 1, extra_time=True, penalties=True, advanced_id=1)
    settle_fixture(conn, 902)
    se = db.get_settlement(conn, loser, 902)
    assert (
        se.result is BetResult.LOSS and se.pnl == -10_000.0
    )  # draw on 90' → home loses
    assert db.get_competitor(conn, loser).bankroll == before - 10_000.0
    print("knockout 1-1 (won on pens) settles as DRAW — home bet LOSES: PASS")

    print("\nALL ACCEPTANCE CRITERIA PASS")


if __name__ == "__main__":
    main()
