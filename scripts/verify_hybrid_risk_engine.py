"""Hybrid risk-engine regression — synthetic, offline, no LLM/network, no live DB.

    uv run python scripts/verify_hybrid_risk_engine.py

Covers the Phase-5 stake-protection layer that sits on top of the model-owned pick:
  * The 1.5% EV gate admits a small real edge but passes a sub-1.5% rounding-noise edge.
  * Half-Kelly only ever shrinks an oversized stake; the per-match cap and aggregate exposure
    bind when they are tighter; exposure-to-zero forces a pass.
  * The 2% minimum-bet floor lifts a small real edge (no trivial bets), bounded by the cap
    and exposure — and never lifts a gated noise edge.
  * The cap ramp: a big edge clipped to 25% at the group bets bigger (50% cap) in the final.
  * A missing/malformed revised distribution earns one retry, then fails closed.

Every test runs against a throwaway temp DB with a stubbed `complete`; nothing touches
the live tournament DB or the network.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worldcup_agents import db
from worldcup_agents import predict as engine
from worldcup_agents.config import ModelSpec
from worldcup_agents.models import (
    Bet,
    Fixture,
    MatchBriefing,
    ModelCall,
    OddsSnapshot,
    Outcome,
    Prediction,
    Stage,
    Team,
)

NOW = datetime.now(timezone.utc)
KICKOFF = NOW + timedelta(days=2)  # far enough out that the kickoff guard never fires
FIXTURE_ID = 9001
MODEL = ModelSpec("Risk Agent", "test/risk-agent")
BANKROLL = 1_000_000.0
FLOOR = 20_000.0  # 2% of $1M
# Shared odds: short-priced home favorite (1.83 -> net 0.83), long away underdog (4.80).
ODDS = OddsSnapshot(
    fixture_id=FIXTURE_ID, captured_at=NOW, bookmaker="consensus", home=1.83, draw=3.55,
    away=4.80,
)


def _single(payload: dict, generation_id: str):
    def fake_complete(model_id, prompt, *, model_name, step, fixture_id=None, **_):
        return json.dumps(payload), ModelCall(
            model_name=model_name, step=step, fixture_id=fixture_id,
            generation_id=generation_id, prompt_text=prompt,
            response_text=json.dumps(payload), created_at=NOW,
        )

    return fake_complete


def _sequence(payloads: list[dict], prefix: str):
    state = {"n": 0}

    def fake_complete(model_id, prompt, *, model_name, step, fixture_id=None, **_):
        i = min(state["n"], len(payloads) - 1)
        state["n"] += 1
        return json.dumps(payloads[i]), ModelCall(
            model_name=model_name, step=step, fixture_id=fixture_id,
            generation_id=f"{prefix}-{i}", prompt_text=prompt,
            response_text=json.dumps(payloads[i]), created_at=NOW,
        )

    return fake_complete, state


def _setup(stage: Stage = Stage.GROUP) -> tuple[sqlite3.Connection, Fixture]:
    path = Path(tempfile.mkdtemp()) / "risk.db"
    conn = db.connect(path)
    db.init_db(conn)  # seeds the 7 competitors at $1M each
    db.upsert_team(conn, Team(id=1, name="Brazil", group="G"))
    db.upsert_team(conn, Team(id=2, name="Morocco", group="G"))
    db.upsert_fixture(
        conn, Fixture(id=FIXTURE_ID, stage=stage, group="G", kickoff=KICKOFF,
                      home_id=1, away_id=2)
    )
    db.upsert_match_briefing(
        conn, MatchBriefing(fixture_id=FIXTURE_ID, created_at=NOW, content="Synthetic.")
    )
    db.upsert_odds_snapshot(conn, ODDS)
    return conn, fixture(conn)


def fixture(conn: sqlite3.Connection) -> Fixture:
    return db.get_fixture(conn, FIXTURE_ID)


def _blind() -> Prediction:
    return Prediction(
        model_name=MODEL.name, fixture_id=FIXTURE_ID, winner=Outcome.HOME,
        p_home=0.45, p_draw=0.30, p_away=0.25, confidence=0.45,
        reasoning="Flat blind read.", created_at=NOW,
    )


def _add_open_bet(conn: sqlite3.Connection, fixture_id: int, stake: float) -> None:
    db.upsert_fixture(
        conn, Fixture(id=fixture_id, stage=Stage.GROUP, group="G", kickoff=KICKOFF,
                      home_id=1, away_id=2)
    )
    db.upsert_bet(
        conn, Bet(model_name=MODEL.name, fixture_id=fixture_id, pick=Outcome.HOME,
                  stake=stake, odds_at_bet=1.83, reasoning="open exposure", created_at=NOW)
    )


def _bet(conn: sqlite3.Connection, fx: Fixture):
    return engine.bet(conn, MODEL, fx, _blind(), ODDS, BANKROLL, "Brazil", "Morocco",
                      force=True)


def _pay(pick: str, stake: float, ph: float, pd: float, pa: float) -> dict:
    return {"p_home_revised": ph, "p_draw_revised": pd, "p_away_revised": pa,
            "pick": pick, "stake": stake, "reasoning": "..."}


def _ev_admits_sub5_edge() -> None:
    # home 0.56 @1.83 -> EV +2.48% (above the 1.5% gate, under the old 5% floor). It BETS;
    # half-Kelly (~$14.9k) is below the 2% floor, so the floor lifts it to $20k.
    conn, fx = _setup()
    engine.complete = _single(_pay("home", 40_000, 0.56, 0.24, 0.20), "g-sub5")
    b = _bet(conn, fx)
    assert b.pick == Outcome.HOME and b.stake == FLOOR, (b.pick, b.stake)
    assert b.engine_adjustment == "min_floor", b.engine_adjustment
    print("the EV gate admits a real sub-5% edge, floored to the 2% minimum: PASS")


def _mid_stake_unchanged() -> None:
    # home 0.60 @1.83 -> EV +9.8%, half-Kelly ~$59k. A $40k request sits between the floor
    # and the Kelly ceiling, so the engine leaves it exactly as asked.
    conn, fx = _setup()
    engine.complete = _single(_pay("home", 40_000, 0.60, 0.24, 0.16), "g-mid")
    b = _bet(conn, fx)
    assert b.pick == Outcome.HOME and b.stake == 40_000, b.stake
    assert b.engine_adjustment is None, b.engine_adjustment
    print("a stake between floor and Kelly is left unchanged: PASS")


def _half_kelly_shrinks() -> None:
    # home 0.60 (EV 9.8%), $200k request. Half-Kelly = 1M*0.5*(0.098/0.83) = 59,036.14.
    conn, fx = _setup()
    engine.complete = _single(_pay("home", 200_000, 0.60, 0.24, 0.16), "g-kelly")
    b = _bet(conn, fx)
    assert abs(b.stake - 59_036.14) < 0.5, b.stake
    assert b.engine_adjustment == "kelly_cap"
    assert b.requested_stake == 200_000
    print("half-Kelly shrinks an oversized requested stake: PASS")


def _floor_lifts_small_real_edge() -> None:
    # away 0.215 @4.80 -> EV +3.2% (a real edge, above the 1.5% gate) but half-Kelly is only
    # ~$4.2k. The 2% floor lifts it to $20k so there are no trivial bets.
    conn, fx = _setup()
    engine.complete = _single(_pay("away", 150_000, 0.55, 0.235, 0.215), "g-floor")
    b = _bet(conn, fx)
    assert b.pick == Outcome.AWAY and b.stake == FLOOR, (b.pick, b.stake)
    assert b.engine_adjustment == "min_floor"
    assert b.requested_stake == 150_000
    print("the 2% floor lifts a small real edge to $20k (no trivial bets): PASS")


def _noise_edge_is_gated() -> None:
    # away 0.21 @4.80 -> EV +0.8%, BELOW the 1.5% gate: a rounding-noise edge is passed, NOT
    # floored into a $20k bet. This is the fix for the EV=0 + floor interaction Codex flagged.
    conn, fx = _setup()
    engine.complete = _single(_pay("away", 150_000, 0.55, 0.24, 0.21), "g-noise")
    b = _bet(conn, fx)
    assert b.is_pass, (b.pick, b.stake)
    assert b.engine_adjustment == "ev_guard"
    assert b.requested_pick == Outcome.AWAY and b.requested_stake == 150_000
    print("a sub-1.5% noise edge is gated to a pass (not floored to $20k): PASS")


def _per_match_cap_binds() -> None:
    # home 0.85 (EV 55.5%): half-Kelly ~$335k, so the group 25% cap ($250k) binds.
    conn, fx = _setup()
    engine.complete = _single(_pay("home", 400_000, 0.85, 0.10, 0.05), "g-cap")
    b = _bet(conn, fx)
    assert b.stake == 250_000, b.stake
    assert b.engine_adjustment == "stake_cap"
    print("25% group cap binds when half-Kelly would allow more: PASS")


def _exposure_cap_trims() -> None:
    # $470k already committed -> $30k of the $500k (50%) budget free, tighter than Kelly/cap.
    conn, fx = _setup()
    _add_open_bet(conn, 999, 470_000)
    engine.complete = _single(_pay("home", 200_000, 0.85, 0.10, 0.05), "g-expo")
    b = _bet(conn, fx)
    assert b.stake == 30_000, b.stake
    assert b.engine_adjustment == "exposure_cap"
    print("aggregate-exposure cap trims the stake to the free budget: PASS")


def _exposure_full_forces_pass() -> None:
    conn, fx = _setup()
    _add_open_bet(conn, 999, 500_000)
    engine.complete = _single(_pay("home", 200_000, 0.85, 0.10, 0.05), "g-full")
    b = _bet(conn, fx)
    assert b.is_pass, (b.pick, b.stake)
    assert b.engine_adjustment == "exposure_cap"
    assert b.requested_pick == Outcome.HOME and b.requested_stake == 200_000
    print("fully-committed exposure forces a pass, request preserved: PASS")


def _stage_ramp_bets_bigger_late() -> None:
    # Kelly is flat (half) at every stage; the PER-MATCH CAP carries the ramp. A big edge
    # (home 0.85 @1.83, half-Kelly ~$334.6k) is clipped to the 25% cap ($250k) at the group,
    # but the 50% final cap lets it through to its half-Kelly size (~$334.6k).
    cg, fg = _setup(Stage.GROUP)
    engine.complete = _single(_pay("home", 400_000, 0.85, 0.10, 0.05), "ramp-g")
    grp = _bet(cg, fg)
    cf, ff = _setup(Stage.FINAL)
    engine.complete = _single(_pay("home", 400_000, 0.85, 0.10, 0.05), "ramp-f")
    fin = _bet(cf, ff)
    assert grp.stake == 250_000 and grp.engine_adjustment == "stake_cap", grp.stake
    assert abs(fin.stake - 334_638.55) < 0.5 and fin.engine_adjustment == "kelly_cap", fin.stake
    assert fin.stake > grp.stake
    print("stage ramp: the per-match cap lets a big edge bet bigger in the final: PASS")


def _retry_then_succeed() -> None:
    conn, fx = _setup()
    stub, state = _sequence(
        [{"pick": "home", "stake": 50_000, "reasoning": "Missing distribution."},
         _pay("home", 50_000, 0.60, 0.24, 0.16)],
        "retry-ok",
    )
    engine.complete = stub
    b = _bet(conn, fx)
    assert state["n"] == 2, state["n"]
    assert b.pick == Outcome.HOME and b.stake == 50_000  # between floor and Kelly, unchanged
    assert b.has_revised_distribution and b.engine_adjustment is None
    print("one retry recovers a malformed distribution: PASS")


def _retry_twice_fails_closed() -> None:
    conn, fx = _setup()
    stub, state = _sequence(
        [{"pick": "home", "stake": 50_000, "reasoning": "Missing once."},
         {"pick": "home", "stake": 50_000, "reasoning": "Missing twice."}],
        "retry-fail",
    )
    engine.complete = stub
    b = _bet(conn, fx)
    assert state["n"] == 2, state["n"]
    assert b.is_pass and b.engine_adjustment == "missing_revised_distribution"
    assert b.requested_pick == Outcome.HOME and b.requested_stake == 50_000
    print("a still-malformed retry fails closed to a pass: PASS")


def main() -> None:
    _ev_admits_sub5_edge()
    _mid_stake_unchanged()
    _half_kelly_shrinks()
    _floor_lifts_small_real_edge()
    _noise_edge_is_gated()
    _per_match_cap_binds()
    _exposure_cap_trims()
    _exposure_full_forces_pass()
    _stage_ramp_bets_bigger_late()
    _retry_then_succeed()
    _retry_twice_fails_closed()
    print("\nAll hybrid risk-engine checks passed.")


if __name__ == "__main__":
    main()
