"""Phase-6 betting-contract regression — synthetic, offline, no network.

    uv run python scripts/verify_market_reconciliation.py

The historical filename is retained because operations and documentation link to it.
Market reconciliation, revised probabilities, EV gates, and Kelly sizing no longer exist.
This script verifies the replacement contract:

* Step 1 persists an odds-hidden distribution with provenance.
* Step 2 exposes only outcomes inside the blind 10-point eligibility window.
* Fixed tiers persist without revised-probability fields.
* Ineligible picks fail closed while preserving the requested action.
* Voluntary passes remain normal.
* Legacy schemas and the human challenger's separate 25% cap still work.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from worldcup_agents import db
from worldcup_agents import predict as prediction_engine
from worldcup_agents.config import HUMAN_MAX_STAKE_FRACTION, ModelSpec
from worldcup_agents.experiment import (
    BET_PROMPT_VERSION,
    BETTING_RULES_VERSION,
    EXPERIMENT_PHASE,
    FORECAST_PROMPT_VERSION,
    HUMAN_BET_VERSION,
    HUMAN_RULES_VERSION,
)
from worldcup_agents.models import (
    Fixture,
    MatchBriefing,
    ModelCall,
    OddsSnapshot,
    Outcome,
    Prediction,
    Stage,
    Team,
)
from worldcup_agents.web import challenger

NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2099, 6, 14, 19, 0, tzinfo=timezone.utc)
MODEL = ModelSpec("Regression Agent", "test/regression-agent")
BANKROLL = 1_000_000.0


def _completion(
    payload: dict,
    generation_id: str,
    inspect_prompt: Callable[[str], None] | None = None,
):
    def fake_complete(
        model_id: str,
        prompt: str,
        *,
        model_name: str,
        step: str,
        fixture_id: int | None = None,
        **_: object,
    ) -> tuple[str, ModelCall]:
        assert model_id == MODEL.model_id
        if inspect_prompt:
            inspect_prompt(prompt)
        text = json.dumps(payload)
        return text, ModelCall(
            model_name=model_name,
            step=step,
            fixture_id=fixture_id,
            generation_id=generation_id,
            prompt_text=prompt,
            response_text=text,
            created_at=NOW,
        )

    return fake_complete


def _setup(
    fixture_id: int = 105,
) -> tuple[sqlite3.Connection, Fixture, MatchBriefing, OddsSnapshot]:
    path = Path(tempfile.mkdtemp()) / "phase6_contract.db"
    conn = db.connect(path)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Haiti", group="C"))
    db.upsert_team(conn, Team(id=2, name="Scotland", group="C"))
    fixture = Fixture(
        id=fixture_id,
        stage=Stage.GROUP,
        group="C",
        kickoff=KICKOFF,
        home_id=1,
        away_id=2,
    )
    db.upsert_fixture(conn, fixture)
    briefing = MatchBriefing(
        fixture_id=fixture.id,
        created_at=NOW,
        content="Scotland have the stronger squad, form, and tactical control.",
    )
    db.upsert_match_briefing(conn, briefing)
    odds = OddsSnapshot(
        fixture_id=fixture.id,
        captured_at=NOW,
        bookmaker="consensus",
        home=6.0,
        draw=4.525,
        away=1.525,
    )
    db.upsert_odds_snapshot(conn, odds)
    return conn, fixture, briefing, odds


def _blind_prediction(fixture_id: int = 105) -> Prediction:
    return Prediction(
        model_name=MODEL.name,
        fixture_id=fixture_id,
        winner=Outcome.AWAY,
        p_home=0.21,
        p_draw=0.26,
        p_away=0.53,
        confidence=0.53,
        reasoning="Scotland are the clear football call.",
        created_at=NOW,
    )


def _verify_legacy_migration() -> None:
    path = Path(tempfile.mkdtemp()) / "legacy.db"
    conn = db.connect(path)
    conn.executescript("""
        CREATE TABLE prediction (
            model_name TEXT NOT NULL,
            fixture_id INTEGER NOT NULL,
            winner TEXT NOT NULL,
            confidence REAL NOT NULL,
            reasoning TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (model_name, fixture_id)
        );
        CREATE TABLE bet (
            model_name TEXT NOT NULL,
            fixture_id INTEGER NOT NULL,
            pick TEXT,
            stake REAL NOT NULL DEFAULT 0,
            odds_at_bet REAL,
            reasoning TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY (model_name, fixture_id)
        );
        INSERT INTO prediction VALUES (
            'Legacy Agent', 1, 'home', 0.55, 'legacy prediction',
            '2026-06-11T12:00:00+00:00'
        );
        INSERT INTO bet VALUES (
            'Legacy Agent', 1, 'home', 1000, 2.0, 'legacy bet',
            '2026-06-11T12:01:00+00:00'
        );
        """)
    db.init_db(conn)

    pred = db.get_prediction(conn, "Legacy Agent", 1)
    bet = db.get_bet(conn, "Legacy Agent", 1)
    assert pred is not None and pred.experiment_phase is None
    assert pred.prompt_version is None and pred.git_commit is None
    assert bet is not None and bet.experiment_phase is None
    assert bet.rules_version is None and bet.odds_snapshot_bookmaker is None
    assert not bet.has_revised_distribution
    assert bet.p_home_revised is None and bet.p_draw_revised is None
    assert bet.p_away_revised is None
    assert bet.requested_pick is None and bet.requested_stake is None
    assert bet.requested_p_revised is None and bet.engine_adjustment is None
    conn.close()
    print("legacy schema migration + nullable Phase-2-to-5 fields: PASS")


def _verify_human_actions() -> None:
    path = Path(tempfile.mkdtemp()) / "human_pass.db"
    original_connect = db.connect
    conn = original_connect(path)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Haiti", group="C"))
    db.upsert_team(conn, Team(id=2, name="Scotland", group="C"))
    fixture = Fixture(
        id=205,
        stage=Stage.GROUP,
        group="C",
        kickoff=KICKOFF,
        home_id=1,
        away_id=2,
    )
    db.upsert_fixture(conn, fixture)
    db.upsert_prediction(
        conn,
        Prediction(
            model_name="Human Regression",
            fixture_id=fixture.id,
            winner=Outcome.AWAY,
            confidence=0.55,
            reasoning="Human blind prediction.",
            created_at=NOW,
        ),
    )
    odds = OddsSnapshot(
        fixture_id=fixture.id,
        captured_at=NOW,
        bookmaker="consensus",
        home=6.0,
        draw=4.525,
        away=1.525,
    )
    db.upsert_odds_snapshot(conn, odds)
    conn.close()

    db.connect = lambda: original_connect(path)
    try:
        response = challenger.place_bet(
            challenger.BetBody(
                fixture_id=fixture.id,
                pick="pass",
                stake=0,
                reasoning="No value at these prices.",
            ),
            name="Human Regression",
        )
        conn = original_connect(path)
        bet = db.get_bet(conn, "Human Regression", fixture.id)
        assert response["pick"] == "pass"
        assert bet is not None and bet.is_pass
        assert bet.prompt_version == HUMAN_BET_VERSION
        assert bet.rules_version == HUMAN_RULES_VERSION
        assert bet.requested_model_id == "human"
        conn.close()

        response = challenger.place_bet(
            challenger.BetBody(
                fixture_id=fixture.id,
                pick="away",
                stake=400_000,
                reasoning="Human oversized request.",
            ),
            name="Human Regression",
        )
        conn = original_connect(path)
        bet = db.get_bet(conn, "Human Regression", fixture.id)
        expected_cap = BANKROLL * HUMAN_MAX_STAKE_FRACTION
        assert response["pick"] == "away" and response["stake"] == expected_cap
        assert bet is not None and bet.pick == Outcome.AWAY
        assert bet.stake == expected_cap and bet.requested_stake == 400_000
        assert bet.engine_adjustment == "stake_cap"
        conn.close()
    finally:
        db.connect = original_connect
    print("human pass + independent flat 25% manual cap: PASS")


def main() -> None:
    conn, fixture, briefing, odds = _setup()

    prediction_engine.complete = _completion(
        {
            "p_home": 0.21,
            "p_draw": 0.26,
            "p_away": 0.53,
            "expected_home_goals": 0.7,
            "expected_away_goals": 1.8,
            "most_likely_score": "0-2",
            "key_factors": ["squad quality", "midfield control"],
            "reasoning": "Scotland are the clear football call.",
        },
        "gen-predict",
    )
    prediction = prediction_engine.predict(
        conn,
        MODEL,
        fixture,
        briefing,
        "Haiti",
        "Scotland",
    )
    assert prediction.winner == Outcome.AWAY
    assert prediction.p_away == 0.53
    assert prediction.experiment_phase == EXPERIMENT_PHASE
    assert prediction.prompt_version == FORECAST_PROMPT_VERSION
    assert prediction.requested_model_id == MODEL.model_id
    assert prediction.call_generation_id == "gen-predict"
    assert prediction.git_commit
    assert db.get_prediction(conn, MODEL.name, fixture.id) == prediction
    assert prediction_engine._eligible_outcomes(prediction) == {Outcome.AWAY: 0.53}
    print("odds-hidden prediction + provenance + eligibility: PASS")

    def inspect_bet_prompt(prompt: str) -> None:
        assert "ONLY eligible outcomes are: away (Scotland) 53%" in prompt
        assert "Passing is a normal decision" in prompt
        assert "stake_pct" in prompt
        assert "revised probability" not in prompt.lower()
        assert "kelly" not in prompt.lower()
        assert "EV gate" not in prompt

    prediction_engine.complete = _completion(
        {
            "pick": "away",
            "stake_pct": 20,
            "reasoning": "Scotland's control deserves the top group-stage tier.",
        },
        "gen-favorite",
        inspect_bet_prompt,
    )
    favorite = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        BANKROLL,
        "Haiti",
        "Scotland",
        force=True,
    )
    assert favorite.pick == Outcome.AWAY and favorite.stake == 200_000
    assert favorite.requested_pick == Outcome.AWAY
    assert favorite.requested_stake == 200_000
    assert favorite.engine_adjustment is None
    assert favorite.p_revised is None and not favorite.has_revised_distribution
    assert favorite.experiment_phase == EXPERIMENT_PHASE
    assert favorite.prompt_version == BET_PROMPT_VERSION
    assert favorite.rules_version == BETTING_RULES_VERSION
    assert favorite.requested_model_id == MODEL.model_id
    assert favorite.call_generation_id == "gen-favorite"
    assert favorite.odds_snapshot_captured_at == odds.captured_at
    assert db.get_bet(conn, MODEL.name, fixture.id) == favorite
    print("eligible 20% tier + Phase-6 persistence contract: PASS")

    conn, fixture, _, odds = _setup(106)
    prediction = _blind_prediction(106)
    prediction_engine.complete = _completion(
        {
            "pick": "home",
            "stake_pct": 20,
            "reasoning": "The payout is tempting.",
        },
        "gen-blocked-longshot",
    )
    blocked = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        BANKROLL,
        "Haiti",
        "Scotland",
        force=True,
    )
    assert blocked.is_pass
    assert blocked.requested_pick == Outcome.HOME
    assert blocked.requested_stake == 200_000
    assert blocked.engine_adjustment == "ineligible_pick"
    assert "32% below the blind top read" in blocked.reasoning
    print("Haiti-style payout chase fails closed, request preserved: PASS")

    conn, fixture, _, odds = _setup(107)
    prediction = _blind_prediction(107)
    prediction_engine.complete = _completion(
        {
            "pick": "pass",
            "stake_pct": 0,
            "reasoning": "The eligible price is too short.",
        },
        "gen-pass",
    )
    passed = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        BANKROLL,
        "Haiti",
        "Scotland",
        force=True,
    )
    assert passed.is_pass and passed.engine_adjustment is None
    assert passed.requested_stake == 0
    print("voluntary pass is normal and unadjusted: PASS")

    eliminated = prediction_engine._record_pass(
        conn,
        MODEL,
        fixture,
        "eliminated — betting disabled",
        odds,
        force=True,
    )
    assert eliminated.is_pass
    assert eliminated.engine_adjustment == "eliminated"
    assert eliminated.prompt_version == BET_PROMPT_VERSION
    assert eliminated.rules_version == BETTING_RULES_VERSION
    print("engine-generated eliminated pass retains Phase-6 labels: PASS")

    _verify_legacy_migration()
    _verify_human_actions()
    print("\nAll Phase-6 betting-contract checks passed.")


if __name__ == "__main__":
    main()
