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

Bust rule (DESIGN §5): if settlement drops a competitor to/below BANKRUPT_FLOOR and a
life remains, reset the bankroll to REBUY_AMOUNT (a "second life") and burn the life;
with no life left, the competitor is eliminated (active=False). A whole matchday settles
as ONE batch (`settle_matchday`) so this check runs once over the day's TOTAL PnL — a
competitor can't be tipped into a re-buy by a mid-day dip a later same-day win erases,
and the day's life-burn no longer depends on which fixture happens to settle first.

Settlement is idempotent (the `settlement` PK guards re-application) and atomic (every
settlement row + competitor standing + ledger entry for the batch in one transaction).
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from . import db
from .config import BANKRUPT_FLOOR, IDLE_DECAY, MAX_LIVES, REBUY_AMOUNT
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


def _settle_competitor(
    comp: Competitor,
    graded: list[tuple[int, BetResult, float, float]],
    at: datetime,
) -> tuple[list[Settlement], Competitor, list[BankrollEntry]]:
    """Apply a BATCH of graded bets for ONE competitor, then run the bust → re-buy /
    elimination rule exactly ONCE on the resulting balance. Pure.

    `graded` is a list of (fixture_id, result, payout, pnl) for that competitor's
    unsettled bets — typically every bet it placed across a single matchday. Each bet
    still gets its own settlement row and `bet_settled` ledger entry (so per-match PnL
    stays auditable), but the bankrupt-floor check sees only the SUMMED balance. Because
    addition is commutative the end balance is order-free, and checking bust once means a
    competitor can no longer be tipped into a re-buy by a mid-day dip that a later same-day
    win would have erased — making a matchday's life-burn independent of settle order.

    Returns the settlement rows, the new standing, and the ledger entries to record (a
    `bet_settled` entry per non-zero-PnL bet, plus one `rebuy` entry if a life is spent).
    """
    balance = comp.bankroll
    lives_used = comp.lives_used
    active = comp.active
    settlements: list[Settlement] = []
    ledger: list[BankrollEntry] = []

    for fixture_id, result, payout, pnl in graded:
        balance += pnl
        settlements.append(
            Settlement(
                model_name=comp.model_name,
                fixture_id=fixture_id,
                result=result,
                payout=payout,
                pnl=pnl,
                settled_at=at,
            )
        )
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
                    # attribute the re-buy to the last bet that settled in the batch
                    fixture_id=graded[-1][0] if graded else None,
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
    return settlements, new, ledger


# ---- Orchestration -------------------------------------------------------


def _settle_fixtures(
    conn: sqlite3.Connection, fixtures: list[Fixture]
) -> list[Settlement]:
    """Grade and apply every unsettled bet across `fixtures` as ONE batch: accumulate
    each competitor's PnL over all the fixtures, then run the bust check once per
    competitor and commit everything atomically. Idempotent — already-settled bets are
    returned untouched and never re-applied. The shared core of `settle_fixture` (one
    fixture) and `settle_matchday` (a whole day)."""
    at = _now()
    already: list[Settlement] = []
    # Group each competitor's still-unsettled bets, in a deterministic (fixture, model)
    # order so the ledger is reproducible. The bust check itself is order-free.
    by_comp: dict[str, list[tuple[int, BetResult, float, float]]] = defaultdict(list)
    for fixture in sorted(fixtures, key=lambda f: f.id):
        for bet in db.list_bets(conn, fixture.id):
            existing = db.get_settlement(conn, bet.model_name, fixture.id)
            if existing is not None:
                already.append(existing)
                continue
            result, payout, pnl = grade_bet(fixture, bet)
            by_comp[bet.model_name].append((fixture.id, result, payout, pnl))

    new_settlements: list[Settlement] = []
    updated_comps: list[Competitor] = []
    all_ledger: list[BankrollEntry] = []
    for model_name in sorted(by_comp):
        comp = db.get_competitor(conn, model_name)
        if comp is None:
            raise ValueError(f"no competitor row for {model_name!r}")
        settlements, new_comp, ledger = _settle_competitor(
            comp, by_comp[model_name], at
        )
        new_settlements.extend(settlements)
        updated_comps.append(new_comp)
        all_ledger.extend(ledger)

    if new_settlements:
        db.record_settlement_batch(conn, new_settlements, updated_comps, all_ledger)
    return already + new_settlements


def settle_fixture(conn: sqlite3.Connection, fixture_id: int) -> list[Settlement]:
    """Grade and apply every bet on a single fixture. Idempotent. (Manual / CLI path —
    the live orchestrator settles a whole matchday at once via `settle_matchday`.)"""
    fixture = db.get_fixture(conn, fixture_id)
    if fixture is None:
        raise ValueError(f"no fixture with id {fixture_id}")
    if fixture.status != MatchStatus.POSTPONED and fixture.result_90() is None:
        raise ValueError(
            f"fixture {fixture_id} is not finished — record a 90-minute result with "
            f"`python -m worldcup_agents.settlement result {fixture_id} <home> <away>` "
            "(or `--postpone`) first"
        )
    return _settle_fixtures(conn, [fixture])


def settle_matchday(conn: sqlite3.Connection, matchday: str) -> list[Settlement]:
    """Grade and apply every bet across one matchday (UTC date, YYYY-MM-DD) as a single
    batch, so each competitor's bust / re-buy check runs ONCE over the day's total PnL
    rather than fixture-by-fixture (DESIGN §5). Idempotent.

    Runs at matchday CLOSE: raises if any fixture that day is still unplayed, since
    settling early would re-introduce the very settle-order dependence this removes. A
    fixture's bankroll impact thus lands a few hours later on busy days — an intentional
    trade for an order-independent leaderboard."""
    fixtures = db.fixtures_on_date(conn, matchday)
    if not fixtures:
        raise ValueError(f"no fixtures on {matchday}")
    unfinished = [
        f.id
        for f in fixtures
        if f.status not in (MatchStatus.FINISHED, MatchStatus.POSTPONED)
    ]
    if unfinished:
        raise ValueError(
            f"matchday {matchday} is not closed — fixtures still unplayed: {unfinished}. "
            "Settlement runs once the day's matches are all resolved."
        )
    return _settle_fixtures(conn, fixtures)


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


# ---- Idle-cash decay (anti-cowardice, DESIGN §5) -------------------------


def apply_idle_decay(conn: sqlite3.Connection, matchday: str) -> list[BankrollEntry]:
    """Bleed `IDLE_DECAY` off each active competitor's UN-staked bankroll for one
    matchday (UTC date, YYYY-MM-DD). Idempotent (skips an already-decayed matchday) and
    atomic. Runs at matchday CLOSE — raises if any fixture that day is still unplayed,
    since decaying before bets are placed would lock in an overstated idle base.

    A pure passer bleeds the full rate; a competitor who risked capital bleeds only on
    the remainder. Decay is a bleed, not a loss: it never triggers bust/elimination.
    """
    if db.matchday_decayed(conn, matchday):
        return []

    fixtures = db.fixtures_on_date(conn, matchday)
    if not fixtures:
        raise ValueError(f"no fixtures on {matchday}")
    unfinished = [
        f.id
        for f in fixtures
        if f.status not in (MatchStatus.FINISHED, MatchStatus.POSTPONED)
    ]
    if unfinished:
        raise ValueError(
            f"matchday {matchday} is not closed — fixtures still unplayed: {unfinished}. "
            "Decay runs after the day's matches are settled."
        )

    staked = db.staked_by_model_on(conn, matchday)
    at = _now()
    updated: list[Competitor] = []
    ledger: list[BankrollEntry] = []
    for comp in db.list_competitors(conn):
        if not comp.active:
            continue  # eliminated competitors are frozen
        idle = max(0.0, comp.bankroll - staked.get(comp.model_name, 0.0))
        delta = round(-IDLE_DECAY * idle, 2)
        if delta == 0:
            continue
        balance = comp.bankroll + delta
        updated.append(
            Competitor(
                model_name=comp.model_name,
                bankroll=balance,
                lives_used=comp.lives_used,
                active=comp.active,
            )
        )
        ledger.append(
            BankrollEntry(
                model_name=comp.model_name,
                at=at,
                delta=delta,
                balance_after=balance,
                reason="idle_decay",
                fixture_id=None,
            )
        )

    db.record_idle_decay(conn, matchday, at.isoformat(), updated, ledger)
    return ledger


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


def _print_settlements(conn: sqlite3.Connection, settlements: list[Settlement]) -> None:
    print(f"{'model':<18}{'fixture':>8}{'result':<8}{'payout':>14}{'pnl':>16}")
    for s in sorted(settlements, key=lambda x: (x.model_name, x.fixture_id)):
        print(
            f"{s.model_name:<18}{s.fixture_id:>8} {s.result.value:<7}"
            f"{s.payout:>14,.0f}{s.pnl:>+16,.0f}"
        )
    print(f"\n{'Bankroll standings':<18}{'bankroll':>16}{'lives':>8}{'status':>10}")
    for c in db.list_competitors(conn):
        status = "active" if c.active else "OUT"
        print(f"{c.model_name:<18}{c.bankroll:>16,.0f}{c.lives_used:>8}{status:>10}")


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
    _print_settlements(conn, settlements)


def _cmd_settle_day(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    settlements = settle_matchday(conn, args.matchday)
    print(f"Matchday {args.matchday} — settled {len(settlements)} bets as one batch\n")
    _print_settlements(conn, settlements)


def _cmd_decay(args: argparse.Namespace) -> None:
    conn = db.connect()
    db.init_db(conn)
    if db.matchday_decayed(conn, args.matchday):
        print(f"Matchday {args.matchday} already decayed — nothing to do.")
        return
    ledger = apply_idle_decay(conn, args.matchday)
    print(f"Idle decay for {args.matchday} (rate {IDLE_DECAY:.3%}):\n")
    print(f"{'model':<18}{'bleed':>14}{'bankroll':>16}")
    for e in sorted(ledger, key=lambda x: x.model_name):
        print(f"{e.model_name:<18}{e.delta:>+14,.2f}{e.balance_after:>16,.0f}")
    if not ledger:
        print("(no active competitors with idle cash)")


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

    sd = sub.add_parser(
        "settle-day",
        help="grade + apply a whole closed matchday as one batch (bust check once)",
    )
    sd.add_argument("matchday", help="UTC date, YYYY-MM-DD")
    sd.set_defaults(func=_cmd_settle_day)

    d = sub.add_parser("decay", help="apply idle-cash decay for a closed matchday")
    d.add_argument("matchday", help="UTC date, YYYY-MM-DD")
    d.set_defaults(func=_cmd_decay)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
