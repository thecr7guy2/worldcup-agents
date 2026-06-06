"""Settlement engine — grade bets, apply PnL, and run the bust / re-buy rule.

A fixture's 90-minute 1X2 result settles every bet placed on it (DESIGN §5–§7):

    WIN   pick == result_90   -> payout = stake*odds, pnl = stake*(odds-1)
    LOSS  pick != result_90   -> payout = 0,           pnl = -stake
    VOID  fixture postponed   -> payout = stake,        pnl = 0   (stake refunded)
    PASS  no bet was placed   -> payout = 0,            pnl = 0

Bankroll uses a NET-PnL model: the stake was never escrowed at bet time, so the
bankroll moves only here, by `pnl`. Settlement is on the 90-minute score ONLY —
a knockout 1–1 won on penalties settles as a DRAW (both teams' 1X2 bets lose).
`Fixture.result_90()` is the single source of truth and ignores ET/penalties.

Bust rule (DESIGN §5): if a settlement drops a competitor to/below BANKRUPT_FLOOR
and a life remains, reset the bankroll to REBUY_AMOUNT (a "second life") and burn
the life; with no life left, the competitor is eliminated (active=False).

Settlement is idempotent (the `settlement` PK guards re-application) and atomic
(settlement row + competitor standing + ledger written in one transaction).
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone

from . import db
from .config import BANKRUPT_FLOOR, MAX_LIVES, REBUY_AMOUNT
from .models import (
    BankrollEntry,
    Bet,
    BetResult,
    Competitor,
    Fixture,
    MatchStatus,
    Settlement,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- Pure grading --------------------------------------------------------


def grade_bet(fixture: Fixture, bet: Bet) -> tuple[BetResult, float, float]:
    """Grade one bet against the fixture's 90-minute result. Pure; no DB.

    Returns (result, payout, pnl). Raises if the fixture is neither postponed nor
    carrying a recorded 90-minute score — settlement must never guess a result.
    """
    if fixture.status == MatchStatus.POSTPONED:
        # Void: stake refunded. In the net-PnL model that is simply no change.
        return BetResult.VOID, bet.stake, 0.0
    if bet.is_pass:
        return BetResult.PASS, 0.0, 0.0

    result_90 = fixture.result_90()
    if result_90 is None:
        raise ValueError(
            f"fixture {fixture.id} has no recorded 90-minute result — "
            f"run `python -m worldcup_agents.settlement result {fixture.id} ...` first"
        )

    odds = bet.odds_at_bet or 0.0
    if bet.pick == result_90:
        payout = bet.stake * odds
        return BetResult.WIN, payout, payout - bet.stake
    return BetResult.LOSS, 0.0, -bet.stake


def _resolve_standing(
    comp: Competitor, pnl: float, fixture_id: int, at: datetime
) -> tuple[Competitor, list[BankrollEntry]]:
    """Apply PnL to a competitor and run the bust → re-buy / elimination rule. Pure.

    Returns the new standing plus the ledger entries to record (a `bet_settled`
    entry for any non-zero PnL, and a `rebuy` entry when a life is spent).
    """
    balance = comp.bankroll + pnl
    lives_used = comp.lives_used
    active = comp.active
    ledger: list[BankrollEntry] = []

    if pnl != 0:
        ledger.append(
            BankrollEntry(
                model_name=comp.model_name,
                at=at,
                delta=pnl,
                balance_after=balance,
                reason="bet_settled",
                fixture_id=fixture_id,
            )
        )

    if balance <= BANKRUPT_FLOOR:
        if lives_used < MAX_LIVES:
            topup = REBUY_AMOUNT - balance
            balance = REBUY_AMOUNT
            lives_used += 1
            ledger.append(
                BankrollEntry(
                    model_name=comp.model_name,
                    at=at,
                    delta=topup,
                    balance_after=balance,
                    reason="rebuy",
                    fixture_id=fixture_id,
                )
            )
        else:
            active = False

    new = Competitor(
        model_name=comp.model_name,
        bankroll=balance,
        lives_used=lives_used,
        active=active,
    )
    return new, ledger


# ---- Orchestration -------------------------------------------------------


def settle_fixture(conn: sqlite3.Connection, fixture_id: int) -> list[Settlement]:
    """Grade and apply every bet on a fixture. Idempotent: already-settled bets are
    returned untouched (no double-application of PnL)."""
    fixture = db.get_fixture(conn, fixture_id)
    if fixture is None:
        raise ValueError(f"no fixture with id {fixture_id}")
    if fixture.status != MatchStatus.POSTPONED and fixture.result_90() is None:
        raise ValueError(
            f"fixture {fixture_id} is not finished — record a 90-minute result with "
            f"`python -m worldcup_agents.settlement result {fixture_id} <home> <away>` "
            "(or `--postpone`) first"
        )

    settlements: list[Settlement] = []
    for bet in db.list_bets(conn, fixture_id):
        existing = db.get_settlement(conn, bet.model_name, fixture_id)
        if existing is not None:
            settlements.append(existing)
            continue

        result, payout, pnl = grade_bet(fixture, bet)
        comp = db.get_competitor(conn, bet.model_name)
        if comp is None:
            raise ValueError(f"no competitor row for {bet.model_name!r}")

        at = _now()
        new_comp, ledger = _resolve_standing(comp, pnl, fixture_id, at)
        s = Settlement(
            model_name=bet.model_name,
            fixture_id=fixture_id,
            result=result,
            payout=payout,
            pnl=pnl,
            settled_at=at,
        )
        db.record_settlement(conn, s, new_comp, ledger)
        settlements.append(s)
    return settlements


def record_result(
    conn: sqlite3.Connection,
    fixture_id: int,
    home_goals: int | None,
    away_goals: int | None,
    *,
    extra_time: bool = False,
    penalties: bool = False,
    advanced_id: int | None = None,
    postponed: bool = False,
) -> Fixture:
    """Record a fixture's outcome so it can be settled. Sets the 90-minute score and
    status (FINISHED, or POSTPONED when `postponed`). This is the manual input for now;
    a later result-ingestion slice (web/API) replaces the manual score."""
    fixture = db.get_fixture(conn, fixture_id)
    if fixture is None:
        raise ValueError(f"no fixture with id {fixture_id}")

    if postponed:
        fixture.status = MatchStatus.POSTPONED
    else:
        if home_goals is None or away_goals is None:
            raise ValueError("home and away goals are required unless --postpone")
        fixture.home_goals_90 = home_goals
        fixture.away_goals_90 = away_goals
        fixture.went_extra_time = extra_time
        fixture.went_penalties = penalties
        fixture.advanced_id = advanced_id
        fixture.status = MatchStatus.FINISHED

    db.upsert_fixture(conn, fixture)
    return fixture


# ---- CLI -----------------------------------------------------------------


def _team_name(conn: sqlite3.Connection, team_id: int | None, label: str | None) -> str:
    if team_id is not None:
        team = db.get_team(conn, team_id)
        if team:
            return team.name
    return label or "?"


def _cmd_result(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    fx = record_result(
        conn,
        args.fixture_id,
        None if args.postpone else args.home_goals,
        None if args.postpone else args.away_goals,
        extra_time=args.et,
        penalties=args.pens,
        advanced_id=args.advanced,
        postponed=args.postpone,
    )
    home = _team_name(conn, fx.home_id, fx.home_label)
    away = _team_name(conn, fx.away_id, fx.away_label)
    if args.postpone:
        print(f"Fixture {fx.id}: {home} vs {away} — POSTPONED (bets will void).")
    else:
        extra = []
        if fx.went_extra_time:
            extra.append("a.e.t.")
        if fx.went_penalties:
            extra.append("pens")
        tag = f" ({', '.join(extra)})" if extra else ""
        print(
            f"Fixture {fx.id}: {home} {fx.home_goals_90}-{fx.away_goals_90} {away}{tag} "
            f"→ 90' result = {fx.result_90().value}."
        )


def _cmd_settle(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    fx = db.get_fixture(conn, args.fixture_id)
    if fx is None:
        raise SystemExit(f"no fixture with id {args.fixture_id}")
    home = _team_name(conn, fx.home_id, fx.home_label)
    away = _team_name(conn, fx.away_id, fx.away_label)

    settlements = settle_fixture(conn, args.fixture_id)
    print(
        f"Fixture {args.fixture_id}: {home} vs {away} — settled {len(settlements)} bets\n"
    )
    print(f"{'model':<18}{'result':<8}{'payout':>14}{'pnl':>16}")
    for s in sorted(settlements, key=lambda x: x.model_name):
        print(
            f"{s.model_name:<18}{s.result.value:<8}{s.payout:>14,.0f}{s.pnl:>+16,.0f}"
        )

    print(f"\n{'Bankroll standings':<18}{'bankroll':>16}{'lives':>8}{'status':>10}")
    for c in db.list_competitors(conn):
        status = "active" if c.active else "OUT"
        print(f"{c.model_name:<18}{c.bankroll:>16,.0f}{c.lives_used:>8}{status:>10}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="worldcup_agents.settlement")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser(
        "result", help="record a fixture's 90-minute result (or postpone)"
    )
    r.add_argument("fixture_id", type=int)
    r.add_argument("home_goals", type=int, nargs="?", help="home goals at 90'")
    r.add_argument("away_goals", type=int, nargs="?", help="away goals at 90'")
    r.add_argument("--et", action="store_true", help="match went to extra time")
    r.add_argument("--pens", action="store_true", help="match was decided on penalties")
    r.add_argument("--advanced", type=int, help="team id that progressed (knockouts)")
    r.add_argument("--postpone", action="store_true", help="mark postponed → bets void")
    r.set_defaults(func=_cmd_result)

    s = sub.add_parser("settle", help="grade + apply all bets for a finished fixture")
    s.add_argument("fixture_id", type=int)
    s.set_defaults(func=_cmd_settle)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
