"""OFFLINE simulation of a simultaneous-match matchday (e.g. the final group round, where
both matches in a group kick off at once). Unlike dry_run.py it spends NO OpenRouter credit:
the model's bet decision is stubbed with a canned table, so the scenario is deterministic and
reproducible. It exercises the REAL code paths we care about:

  - predict.bet()  -> the live exposure note the agent sees as it bets several still-unsettled
                      matches off one bankroll (db.open_exposure),
  - settlement.settle_matchday() -> all of the day's matches settle in ONE batch with the bust
                      check run ONCE over the day's total PnL (order-independent).

    uv run python scripts/dry_run_simultaneous.py
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from worldcup_agents import db, predict, settlement
from worldcup_agents.config import (
    BANKRUPT_FLOOR,
    MAX_STAKE_FRACTION,
    PREDICTION_MODELS,
)
from worldcup_agents.models import (
    Fixture,
    MatchStatus,
    ModelCall,
    OddsSnapshot,
    Outcome,
    Prediction,
    Stage,
    Team,
)

UTC = timezone.utc
NOW = datetime(2026, 6, 27, 18, 0, tzinfo=UTC)
KO = datetime(2026, 6, 27, 19, 0, tzinfo=UTC)  # all four kick off AT ONCE
MATCHDAY = "2026-06-27"

# Three of the real competitors, relabelled here only for narration.
AGGRO, PICKY, ROPES = (m.name for m in PREDICTION_MODELS[:3])

# Four simultaneous fixtures: two groups (A: 9001/9002, B: 9003/9004), both final rounds.
FIXTURES = [
    (9001, "Atlas", "Boreal", "A", 2.50, 3.30, 2.80),
    (9002, "Cobalt", "Dune", "A", 2.10, 3.40, 3.50),
    (9003, "Ember", "Frost", "B", 2.00, 3.20, 4.00),
    (9004, "Gale", "Harbor", "B", 1.90, 3.50, 4.20),
]
# Real 90' outcomes (home_goals, away_goals) -> who actually wins each match.
RESULTS = {9001: (0, 1), 9002: (0, 1), 9003: (0, 1), 9004: (1, 0)}

# Canned bet decision per (competitor, fixture): (pick, stake tier %). "pass" = sit it out.
#   AGGRO  requests the 20% group cap on all four -> the 50% exposure ceiling trims/blocks.
#   PICKY  bets one match only                 -> disciplined, low exposure.
#   ROPES  starts the day already short ($16k)  -> dips to the floor mid-batch, then recovers.
DECISIONS = {
    AGGRO: {
        9001: ("home", 20),
        9002: ("home", 20),
        9003: ("home", 20),
        9004: ("home", 20),
    },
    PICKY: {
        9001: ("pass", 0),
        9002: ("away", 15),
        9003: ("pass", 0),
        9004: ("pass", 0),
    },
    ROPES: {
        9001: ("home", 20),
        9002: ("home", 20),
        9003: ("away", 20),
        9004: ("home", 20),
    },
}
START_BANKROLL = {ROPES: 16_000.0}  # others keep the seeded $1,000,000


def _seed(path: Path):
    conn = db.connect(path)
    db.init_db(conn)
    tid = 901
    for fid, home, away, grp, *_ in FIXTURES:
        for name in (home, away):
            db.upsert_team(conn, Team(id=tid, name=name, group=grp))
            tid += 1
    # map team names -> ids
    name2id = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM team")}
    for fid, home, away, grp, oh, od, oa in FIXTURES:
        db.upsert_fixture(
            conn,
            Fixture(
                id=fid,
                stage=Stage.GROUP,
                group=grp,
                kickoff=KO,
                home_id=name2id[home],
                away_id=name2id[away],
                status=MatchStatus.SCHEDULED,
            ),
        )
        db.upsert_odds_snapshot(
            conn,
            OddsSnapshot(
                fixture_id=fid,
                captured_at=NOW,
                bookmaker="consensus",
                home=oh,
                draw=od,
                away=oa,
            ),
        )
    for name, bankroll in START_BANKROLL.items():
        conn.execute(
            "UPDATE competitor SET bankroll = ? WHERE model_name = ?", (bankroll, name)
        )
    conn.commit()
    return conn


def _stub_complete(decisions_for_model):
    """Return a fake llm.complete that answers from the canned table and records the prompt."""
    captured = {}

    def fake(model_id, prompt, **kw):
        fid = kw.get("fixture_id")
        captured[fid] = prompt
        pick, stake_pct = decisions_for_model[fid]
        return (
            f'{{"pick": "{pick}", "stake_pct": {stake_pct}, "reasoning": "canned"}}',
            ModelCall(
                model_name=kw.get("model_name"),
                step="bet",
                fixture_id=fid,
                created_at=NOW,
            ),
        )

    return fake, captured


def _exposure_line(prompt: str) -> str | None:
    for part in prompt.split(". "):
        if "still awaiting a result" in part:
            return "NOTE: " + part.split("NOTE:", 1)[1].strip() + "."
    return None


def main() -> None:
    conn = _seed(Path(tempfile.mkdtemp(prefix="wc_sim_")) / "sim.db")
    models = {m.name: m for m in PREDICTION_MODELS[:3]}

    print("=" * 78)
    print("SIMULTANEOUS-MATCHDAY DRY RUN —", MATCHDAY)
    print(f"  4 matches all kicking off at {KO:%H:%M} UTC (two groups' final rounds).")
    print(
        f"  Per-match cap: {MAX_STAKE_FRACTION:.0%} of bankroll · bust floor "
        f"${BANKRUPT_FLOOR:,.0f}."
    )
    print("  Competitors:")
    for name in models:
        bk = db.get_competitor(conn, name).bankroll
        tag = " (starts the day SHORT)" if name in START_BANKROLL else ""
        print(f"    · {name:<16} ${bk:>12,.0f}{tag}")
    print("=" * 78)

    # --- BET PHASE: fixture-major, exactly like the orchestrator's due_for_bet loop ---
    print("\n### BET PHASE — odds shown, stakes sized; watch the exposure note climb\n")
    fx = {fid: db.get_fixture(conn, fid) for fid, *_ in FIXTURES}
    teamname = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM team")}
    orig = predict.complete
    try:
        for fid, home, away, grp, oh, od, oa in FIXTURES:
            print(
                f"-- Match {fid}  (Group {grp})  {home} vs {away} "
                f"[odds {oh}/{od}/{oa}] --"
            )
            for name, model in models.items():
                requested_pick = DECISIONS[name][fid][0]
                winner = (
                    Outcome(requested_pick)
                    if requested_pick in {"home", "draw", "away"}
                    else Outcome.HOME
                )
                pred = Prediction(
                    model_name=name,
                    fixture_id=fid,
                    winner=winner,
                    confidence=0.60,
                    reasoning="canned",
                    created_at=NOW,
                )
                odds = db.consensus_odds(conn, fid)
                bankroll = db.get_competitor(conn, name).bankroll
                fake, captured = _stub_complete(DECISIONS[name])
                predict.complete = fake
                b = predict.bet(
                    conn, model, fx[fid], pred, odds, bankroll, home, away, force=True
                )
                verdict = (
                    f"{b.pick.value.upper()} ${b.stake:,.0f} @ {b.odds_at_bet}"
                    if not b.is_pass
                    else "pass"
                )
                note = _exposure_line(captured[fid])
                print(f"   {name:<16} {verdict}")
                if note:
                    print(f"   {'':<16}   ↳ saw: {note}")
            print()
    finally:
        predict.complete = orig

    # --- SETTLE PHASE: record results, then settle the WHOLE DAY as one batch ---
    print("### SETTLE PHASE — record results, then settle_matchday (ONE batch)\n")
    for fid, (hg, ag) in RESULTS.items():
        settlement.record_result(conn, fid, hg, ag)
        f = fx[fid]
        print(
            f"   Match {fid}: {teamname[f.home_id]} {hg}-{ag} {teamname[f.away_id]} "
            f"→ 90' result = {db.get_fixture(conn, fid).result_90().value}"
        )
    print()

    settlements = settlement.settle_matchday(conn, MATCHDAY)
    print(
        f"settle_matchday('{MATCHDAY}') settled {len(settlements)} bets in one batch.\n"
    )
    print(f"   {'competitor':<16}{'fixture':>8}{'result':>8}{'pnl':>14}")
    for s in sorted(settlements, key=lambda x: (x.model_name, x.fixture_id)):
        print(
            f"   {s.model_name:<16}{s.fixture_id:>8}{s.result.value:>8}{s.pnl:>+14,.0f}"
        )

    print(f"\n   {'FINAL STANDINGS':<16}{'bankroll':>16}{'lives':>8}{'status':>10}")
    for name in models:
        c = db.get_competitor(conn, name)
        print(
            f"   {name:<16}{c.bankroll:>16,.0f}{c.lives_used:>8}"
            f"{'active' if c.active else 'OUT':>10}"
        )

    # --- The order-independence payoff, read straight from ROPES' real ledger ---
    print(f"\n### Why batching matters — {ROPES}'s settlement ledger this matchday:\n")
    floor_touched = False
    for e in db.list_bankroll_history(conn, ROPES):
        if e.reason == "bet_settled":
            flag = (
                "  ← at/below the bust floor!"
                if e.balance_after <= BANKRUPT_FLOOR
                else ""
            )
            if flag:
                floor_touched = True
            print(
                f"   match {e.fixture_id}:  {e.delta:>+12,.0f}  →  balance "
                f"${e.balance_after:>12,.0f}{flag}"
            )
    final = db.get_competitor(conn, ROPES)
    print()
    if floor_touched and final.lives_used == 0:
        print(
            f"   {ROPES} touched the ${BANKRUPT_FLOOR:,.0f} floor MID-batch, but the bust"
        )
        print(
            "   check runs ONCE over the day's total — final balance "
            f"${final.bankroll:,.0f}, 0 lives spent."
        )
        print(
            "   Per-fixture settling would have triggered a re-buy at that dip and burned"
        )
        print("   a life — purely an artifact of settle order. Batching removes it.")
    else:
        print("   (No floor dip in this run.)")
    print("\n✅ Simulation complete — no OpenRouter credit spent; deterministic.")


if __name__ == "__main__":
    main()
