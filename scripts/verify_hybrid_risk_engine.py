"""Phase-6 coherent tier-betting regression — synthetic, offline, no network.

    uv run python scripts/verify_hybrid_risk_engine.py

The historical filename is retained for operations compatibility. The Phase-5
EV/Kelly engine is gone; this now verifies:
  * the 10-point blind-forecast eligibility window,
  * fixed conviction tiers and aggressive stage ceilings,
  * normal voluntary passes,
  * ineligible longshots failing closed,
  * aggregate-exposure trimming,
  * provenance and legacy winner-only fallback behavior.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worldcup_agents import db
from worldcup_agents import predict as engine
from worldcup_agents.config import (
    BET_ELIGIBILITY_WINDOW,
    ModelSpec,
    stage_stake_tiers,
)
from worldcup_agents.llm import LLMError
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
KICKOFF = NOW + timedelta(days=2)
FIXTURE_ID = 9001
MODEL = ModelSpec("Tier Agent", "test/tier-agent")
BANKROLL = 1_000_000.0
ODDS = OddsSnapshot(
    fixture_id=FIXTURE_ID,
    captured_at=NOW,
    bookmaker="consensus",
    home=6.0,
    draw=4.525,
    away=1.525,
)


def _completion(payload: dict, generation_id: str = "tier-gen"):
    def fake_complete(model_id, prompt, *, model_name, step, fixture_id=None, **_):
        return json.dumps(payload), ModelCall(
            model_name=model_name,
            step=step,
            fixture_id=fixture_id,
            generation_id=generation_id,
            prompt_text=prompt,
            response_text=json.dumps(payload),
            created_at=NOW,
        )

    return fake_complete


def _completion_sequence(responses: list[str | dict], prefix: str):
    state = {"calls": 0, "prompts": []}

    def fake_complete(model_id, prompt, *, model_name, step, fixture_id=None, **_):
        index = state["calls"]
        state["calls"] += 1
        state["prompts"].append(prompt)
        response = responses[min(index, len(responses) - 1)]
        text = response if isinstance(response, str) else json.dumps(response)
        return text, ModelCall(
            model_name=model_name,
            step=step,
            fixture_id=fixture_id,
            generation_id=f"{prefix}-{index}",
            prompt_text=prompt,
            response_text=text,
            created_at=NOW,
        )

    return fake_complete, state


def _setup(stage: Stage = Stage.GROUP) -> tuple:
    path = Path(tempfile.mkdtemp()) / "tier.db"
    conn = db.connect(path)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Haiti", group="C"))
    db.upsert_team(conn, Team(id=2, name="Scotland", group="C"))
    db.upsert_fixture(
        conn,
        Fixture(
            id=FIXTURE_ID,
            stage=stage,
            group="C",
            kickoff=KICKOFF,
            home_id=1,
            away_id=2,
        ),
    )
    db.upsert_match_briefing(
        conn,
        MatchBriefing(
            fixture_id=FIXTURE_ID,
            created_at=NOW,
            content="Synthetic.",
        ),
    )
    db.upsert_odds_snapshot(conn, ODDS)
    return conn, db.get_fixture(conn, FIXTURE_ID)


def _prediction(
    p_home: float = 0.21,
    p_draw: float = 0.26,
    p_away: float = 0.53,
) -> Prediction:
    probabilities = {
        Outcome.HOME: p_home,
        Outcome.DRAW: p_draw,
        Outcome.AWAY: p_away,
    }
    winner = max(probabilities, key=probabilities.get)
    return Prediction(
        model_name=MODEL.name,
        fixture_id=FIXTURE_ID,
        winner=winner,
        p_home=p_home,
        p_draw=p_draw,
        p_away=p_away,
        confidence=probabilities[winner],
        reasoning="Blind football read.",
        created_at=NOW,
    )


def _bet(conn, fixture, prediction, pick: str, stake_pct: object):
    engine.complete = _completion(
        {
            "pick": pick,
            "stake_pct": stake_pct,
            "reasoning": "Football case and price judgment.",
        }
    )
    return engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        ODDS,
        BANKROLL,
        "Haiti",
        "Scotland",
        force=True,
    )


def _add_open_bet(conn, fixture_id: int, stake: float) -> None:
    db.upsert_fixture(
        conn,
        Fixture(
            id=fixture_id,
            stage=Stage.GROUP,
            group="C",
            kickoff=KICKOFF,
            home_id=1,
            away_id=2,
        ),
    )
    db.upsert_bet(
        conn,
        Bet(
            model_name=MODEL.name,
            fixture_id=fixture_id,
            pick=Outcome.AWAY,
            stake=stake,
            odds_at_bet=1.525,
            created_at=NOW,
        ),
    )


def main() -> None:
    clear = _prediction()
    assert engine._eligible_outcomes(clear) == {Outcome.AWAY: 0.53}

    close = _prediction(0.40, 0.25, 0.35)
    assert engine._eligible_outcomes(close) == {
        Outcome.HOME: 0.40,
        Outcome.AWAY: 0.35,
    }

    boundary = _prediction(0.40, 0.30, 0.30)
    assert set(engine._eligible_outcomes(boundary)) == {
        Outcome.HOME,
        Outcome.DRAW,
        Outcome.AWAY,
    }
    assert BET_ELIGIBILITY_WINDOW == 0.10
    print("10-point eligibility window (clear / close / inclusive boundary): PASS")

    conn, fixture = _setup()
    blocked = _bet(conn, fixture, clear, "home", 20)
    assert blocked.is_pass
    assert blocked.requested_pick == Outcome.HOME
    assert blocked.requested_stake == 200_000
    assert blocked.engine_adjustment == "ineligible_pick"
    assert "outside the 10% eligibility window" in blocked.reasoning
    print("clear longshot contradiction is rejected: PASS")

    conn, fixture = _setup()
    favorite = _bet(conn, fixture, clear, "away", 20)
    assert favorite.pick == Outcome.AWAY and favorite.stake == 200_000
    assert favorite.engine_adjustment is None
    assert favorite.p_revised is None and not favorite.has_revised_distribution
    assert favorite.requested_pick == Outcome.AWAY
    assert favorite.requested_stake == 200_000
    assert favorite.call_generation_id == "tier-gen"
    assert db.get_bet(conn, MODEL.name, FIXTURE_ID) == favorite
    print("top read accepts a large fixed tier with provenance: PASS")

    conn, fixture = _setup()
    close_second = _bet(conn, fixture, close, "away", "20%")
    assert close_second.pick == Outcome.AWAY and close_second.stake == 200_000
    assert close_second.engine_adjustment is None
    print("close second choice remains fully bettable: PASS")

    conn, fixture = _setup()
    passed = _bet(conn, fixture, clear, "pass", 0)
    assert passed.is_pass and passed.engine_adjustment is None
    assert passed.requested_stake == 0
    print("voluntary pass is a normal unadjusted action: PASS")

    conn, fixture = _setup()
    invalid_tier = _bet(conn, fixture, clear, "away", 12)
    assert invalid_tier.is_pass
    assert invalid_tier.requested_stake == 120_000
    assert invalid_tier.engine_adjustment == "invalid_tier"
    print("arbitrary percentage outside the fixed ladder is rejected: PASS")

    conn, fixture = _setup()
    recovery_stub, recovery_state = _completion_sequence(
        [
            "I choose Scotland at the top tier.",
            {
                "pick": "away",
                "stake_pct": 20,
                "reasoning": "Scotland remain the clear football call.",
            },
        ],
        "format-retry",
    )
    engine.complete = recovery_stub
    recovered = engine.bet(
        conn,
        MODEL,
        fixture,
        clear,
        ODDS,
        BANKROLL,
        "Haiti",
        "Scotland",
        force=True,
    )
    assert recovered.pick == Outcome.AWAY and recovered.stake == 200_000
    assert recovered.call_generation_id == "format-retry-1"
    assert recovery_state["calls"] == 2
    assert "FORMAT CORRECTION ONLY" in recovery_state["prompts"][1]
    assert "I choose Scotland at the top tier." in recovery_state["prompts"][1]
    logged = conn.execute(
        "SELECT COUNT(*) FROM model_call WHERE model_name = ? AND fixture_id = ?",
        (MODEL.name, FIXTURE_ID),
    ).fetchone()[0]
    assert logged == 2

    conn, fixture = _setup()
    failure_stub, failure_state = _completion_sequence(
        ["not json", "still not json"],
        "format-fail",
    )
    engine.complete = failure_stub
    try:
        engine.bet(
            conn,
            MODEL,
            fixture,
            clear,
            ODDS,
            BANKROLL,
            "Haiti",
            "Scotland",
            force=True,
        )
    except LLMError:
        pass
    else:
        raise AssertionError("two malformed responses should raise LLMError")
    assert failure_state["calls"] == 2
    assert db.get_bet(conn, MODEL.name, FIXTURE_ID) is None
    logged = conn.execute(
        "SELECT COUNT(*) FROM model_call WHERE model_name = ? AND fixture_id = ?",
        (MODEL.name, FIXTURE_ID),
    ).fetchone()[0]
    assert logged == 2
    print(
        "malformed JSON retries once, logs both calls, then succeeds or fails loudly: PASS"
    )

    assert stage_stake_tiers(Stage.GROUP.value) == (0.05, 0.10, 0.15, 0.20)
    assert stage_stake_tiers(Stage.R16.value)[-1] == 0.25
    assert stage_stake_tiers(Stage.QF.value)[-1] == 0.30

    conn, fixture = _setup(Stage.GROUP)
    group_capped = _bet(conn, fixture, clear, "away", 25)
    assert group_capped.pick == Outcome.AWAY
    assert group_capped.requested_stake == 250_000
    assert group_capped.stake == 200_000
    assert group_capped.engine_adjustment == "stage_cap"

    conn, fixture = _setup(Stage.QF)
    knockout = _bet(conn, fixture, clear, "away", 30)
    assert knockout.pick == Outcome.AWAY and knockout.stake == 300_000
    assert knockout.engine_adjustment is None
    print("stage tier ceilings (20% group / 25% R16 / 30% QF+): PASS")

    conn, fixture = _setup()
    _add_open_bet(conn, 999, 450_000)
    trimmed = _bet(conn, fixture, clear, "away", 20)
    assert trimmed.pick == Outcome.AWAY and trimmed.stake == 50_000
    assert trimmed.engine_adjustment == "exposure_cap"

    conn, fixture = _setup()
    _add_open_bet(conn, 999, 500_000)
    full = _bet(conn, fixture, clear, "away", 20)
    assert full.is_pass and full.engine_adjustment == "exposure_cap"
    print("50% aggregate exposure trims or blocks the requested tier: PASS")

    legacy = Prediction(
        model_name=MODEL.name,
        fixture_id=FIXTURE_ID,
        winner=Outcome.AWAY,
        confidence=0.55,
        reasoning="Legacy winner-only forecast.",
        created_at=NOW,
    )
    assert engine._eligible_outcomes(legacy) == {Outcome.AWAY: 0.55}
    print("legacy winner-only forecasts authorize only their recorded winner: PASS")

    print("\nAll coherent tier-betting checks passed.")


if __name__ == "__main__":
    main()
