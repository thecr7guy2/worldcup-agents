"""Market-reconciliation regression test — synthetic, offline, no LLM/network.

    uv run python scripts/verify_market_reconciliation.py

Reproduces the Canada-Bosnia failure shape: a flat blind forecast makes the favorite
look negative-EV and the underdog look attractive. Verifies that Step 2 can revise
toward the market, that the EV guard uses the revised probability, that missing/invalid
revised probabilities fail closed, and that prediction/bet provenance survives persistence.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from worldcup_agents import db
from worldcup_agents import predict as prediction_engine
from worldcup_agents.config import MIN_BET_EV, ModelSpec
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

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2099, 6, 12, 19, 0, tzinfo=timezone.utc)
MODEL = ModelSpec("Regression Agent", "test/regression-agent")


def _completion(payload: dict, generation_id: str):
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


def _setup() -> tuple[sqlite3.Connection, Fixture, MatchBriefing, OddsSnapshot]:
    path = Path(tempfile.mkdtemp()) / "market_reconciliation.db"
    conn = db.connect(path)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Canada", group="B"))
    db.upsert_team(conn, Team(id=2, name="Bosnia and Herzegovina", group="B"))
    fixture = Fixture(
        id=105,
        stage=Stage.GROUP,
        group="B",
        kickoff=KICKOFF,
        home_id=1,
        away_id=2,
    )
    db.upsert_fixture(conn, fixture)
    briefing = MatchBriefing(
        fixture_id=fixture.id,
        created_at=NOW,
        content="Synthetic shared briefing for the market-reconciliation regression.",
    )
    db.upsert_match_briefing(conn, briefing)
    odds = OddsSnapshot(
        fixture_id=fixture.id,
        captured_at=NOW,
        bookmaker="consensus",
        home=1.83,
        draw=3.55,
        away=4.80,
    )
    db.upsert_odds_snapshot(conn, odds)
    return conn, fixture, briefing, odds


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
    print("legacy schema migration + nullable provenance: PASS")


def _verify_human_actions() -> None:
    path = Path(tempfile.mkdtemp()) / "human_pass.db"
    original_connect = db.connect
    conn = original_connect(path)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Canada", group="B"))
    db.upsert_team(conn, Team(id=2, name="Bosnia and Herzegovina", group="B"))
    fixture = Fixture(
        id=205,
        stage=Stage.GROUP,
        group="B",
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
            winner=Outcome.HOME,
            confidence=0.55,
            reasoning="Human blind prediction.",
            created_at=NOW,
        ),
    )
    odds = OddsSnapshot(
        fixture_id=fixture.id,
        captured_at=NOW,
        bookmaker="consensus",
        home=1.83,
        draw=3.55,
        away=4.80,
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
        assert bet.requested_pick is None and bet.requested_stake == 0
        assert bet.engine_adjustment is None
        assert bet.prompt_version == HUMAN_BET_VERSION
        assert bet.rules_version == HUMAN_RULES_VERSION
        assert bet.requested_model_id == "human"
        assert bet.odds_snapshot_bookmaker == odds.bookmaker
        assert bet.odds_snapshot_captured_at == odds.captured_at
        conn.close()

        response = challenger.place_bet(
            challenger.BetBody(
                fixture_id=fixture.id,
                pick="home",
                stake=400_000,
                reasoning="Human oversized request.",
            ),
            name="Human Regression",
        )
        conn = original_connect(path)
        bet = db.get_bet(conn, "Human Regression", fixture.id)
        assert response["pick"] == "home" and response["stake"] == 250_000
        assert bet is not None and bet.pick == Outcome.HOME
        assert bet.stake == 250_000 and bet.requested_stake == 400_000
        assert bet.requested_pick == Outcome.HOME
        assert bet.engine_adjustment == "stake_cap"
        conn.close()
    finally:
        db.connect = original_connect
    print("human pass snapshot + requested/final cap action: PASS")


def main() -> None:
    conn, fixture, briefing, odds = _setup()

    prediction_engine.complete = _completion(
        {
            "p_home": 0.43,
            "p_draw": 0.29,
            "p_away": 0.28,
            "expected_home_goals": 1.5,
            "expected_away_goals": 1.0,
            "most_likely_score": "1-0",
            "key_factors": ["form", "home crowd"],
            "reasoning": "Canada is the likeliest winner, but the blind forecast is flat.",
        },
        "gen-predict",
    )
    prediction = prediction_engine.predict(
        conn,
        MODEL,
        fixture,
        briefing,
        "Canada",
        "Bosnia and Herzegovina",
    )
    assert prediction.p_home == 0.43
    assert prediction.experiment_phase == EXPERIMENT_PHASE
    assert prediction.prompt_version == FORECAST_PROMPT_VERSION
    assert prediction.requested_model_id == MODEL.model_id
    assert prediction.call_generation_id == "gen-predict"
    assert prediction.git_commit
    assert db.get_prediction(conn, MODEL.name, fixture.id) == prediction
    print("prediction provenance round trip: PASS")

    blind_home_ev = prediction.p_home * odds.home - 1
    blind_away_ev = prediction.p_away * odds.away - 1
    assert blind_home_ev < 0
    assert blind_away_ev > MIN_BET_EV

    rounded, issue = prediction_engine._parse_revised_distribution(
        {
            "p_home_revised": 0.600,
            "p_draw_revised": 0.240,
            "p_away_revised": 0.159,
        }
    )
    assert issue is None and rounded is not None
    assert abs(sum(rounded.values()) - 1.0) < 1e-12
    rejected, issue = prediction_engine._parse_revised_distribution(
        {
            "p_home_revised": 0.60,
            "p_draw_revised": 0.40,
            "p_away_revised": 0.20,
        }
    )
    assert rejected is None and issue == "invalid_revised_distribution"
    all_evs = prediction_engine._revised_evs(rounded, odds)
    assert set(all_evs) == {Outcome.HOME, Outcome.DRAW, Outcome.AWAY}
    assert all_evs[Outcome.HOME] > MIN_BET_EV
    assert all_evs[Outcome.AWAY] < MIN_BET_EV
    print("full distribution normalization + all-outcome EV calculation: PASS")

    prediction_engine.complete = _completion(
        {
            "p_home_revised": 0.60,
            "p_draw_revised": 0.24,
            "p_away_revised": 0.16,
            "pick": "home",
            "stake": 100_000,
            "reasoning": "The market corrects the flat forecast; Canada remains value.",
        },
        "gen-favorite",
    )
    favorite = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        1_000_000,
        "Canada",
        "Bosnia and Herzegovina",
        force=True,
    )
    # The reconciled favorite is bettable (not auto-passed); half-Kelly then sizes the stake
    # down from the requested 100k: EV 0.098 at 1.83 -> 1M * 0.5 * (0.098/0.83) = 59,036.14.
    assert favorite.pick == Outcome.HOME
    assert abs(favorite.stake - 59_036.14) < 0.5
    assert favorite.p_revised == 0.60
    assert favorite.has_revised_distribution
    assert favorite.p_home_revised == 0.60
    assert favorite.p_draw_revised == 0.24
    assert favorite.p_away_revised == 0.16
    assert favorite.requested_pick == Outcome.HOME
    assert favorite.requested_stake == 100_000
    assert favorite.requested_p_revised == 0.60
    assert favorite.engine_adjustment == "kelly_cap"
    assert favorite.experiment_phase == EXPERIMENT_PHASE
    assert favorite.prompt_version == BET_PROMPT_VERSION
    assert favorite.rules_version == BETTING_RULES_VERSION
    assert favorite.requested_model_id == MODEL.model_id
    assert favorite.call_generation_id == "gen-favorite"
    assert favorite.odds_snapshot_bookmaker == odds.bookmaker
    assert favorite.odds_snapshot_captured_at == odds.captured_at
    assert favorite.git_commit
    assert db.get_bet(conn, MODEL.name, fixture.id) == favorite
    print("reconciled favorite bet + provenance round trip: PASS")

    prediction_engine.complete = _completion(
        {
            "p_home_revised": 0.56,
            "p_draw_revised": 0.26,
            "p_away_revised": 0.18,
            "pick": "pass",
            "stake": 0,
            "reasoning": "No offered outcome clears my required edge.",
        },
        "gen-voluntary-pass",
    )
    voluntary_pass = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        1_000_000,
        "Canada",
        "Bosnia and Herzegovina",
        force=True,
    )
    assert voluntary_pass.is_pass and voluntary_pass.engine_adjustment is None
    assert voluntary_pass.has_revised_distribution
    assert voluntary_pass.p_revised is None
    assert voluntary_pass.p_home_revised == 0.56
    print("voluntary pass retains complete revised distribution: PASS")

    prediction_engine.complete = _completion(
        {
            "p_home_revised": 0.56,
            "p_draw_revised": 0.24,
            "p_away_revised": 0.20,
            "pick": "away",
            "stake": 150_000,
            "reasoning": "The blind underdog edge does not survive market reconciliation.",
        },
        "gen-phantom",
    )
    phantom = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        1_000_000,
        "Canada",
        "Bosnia and Herzegovina",
        force=True,
    )
    assert phantom.is_pass
    assert phantom.requested_pick == Outcome.AWAY
    assert phantom.requested_stake == 150_000
    assert phantom.requested_p_revised == 0.20
    assert phantom.has_revised_distribution
    assert phantom.engine_adjustment == "ev_guard"
    assert "by revised probability" in phantom.reasoning
    assert phantom.call_generation_id == "gen-phantom"
    assert phantom.odds_snapshot_captured_at == odds.captured_at
    print("phantom underdog edge rejected by revised probability: PASS")

    prediction_engine.complete = _completion(
        {
            "pick": "away",
            "stake": 150_000,
            "reasoning": "Legacy response with no revised probability.",
        },
        "gen-fallback-positive",
    )
    missing_revised = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        1_000_000,
        "Canada",
        "Bosnia and Herzegovina",
        force=True,
    )
    assert missing_revised.is_pass
    assert missing_revised.p_revised is None
    assert missing_revised.requested_pick == Outcome.AWAY
    assert missing_revised.requested_stake == 150_000
    assert missing_revised.requested_p_revised is None
    assert not missing_revised.has_revised_distribution
    assert missing_revised.engine_adjustment == "missing_revised_distribution"
    assert "revised EV could not be verified" in missing_revised.reasoning

    prediction_engine.complete = _completion(
        {
            "p_home_revised": "NaN",
            "p_draw_revised": 0.24,
            "p_away_revised": 0.16,
            "pick": "home",
            "stake": 150_000,
            "reasoning": "Invalid revised distribution must fail closed.",
        },
        "gen-fallback-negative",
    )
    invalid_revised = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        1_000_000,
        "Canada",
        "Bosnia and Herzegovina",
        force=True,
    )
    assert invalid_revised.is_pass
    assert invalid_revised.requested_pick == Outcome.HOME
    assert invalid_revised.requested_stake == 150_000
    assert invalid_revised.requested_p_revised is None
    assert not invalid_revised.has_revised_distribution
    assert invalid_revised.engine_adjustment == "invalid_revised_distribution"
    assert "revised EV could not be verified" in invalid_revised.reasoning
    print("missing/invalid revised distribution fails closed: PASS")

    prediction_engine.complete = _completion(
        {
            "p_home_revised": 0.85,
            "p_draw_revised": 0.10,
            "p_away_revised": 0.05,
            "pick": "home",
            "stake": 400_000,
            "reasoning": "A big edge whose half-Kelly size still exceeds the 25% hard cap.",
        },
        "gen-cap",
    )
    capped = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        1_000_000,
        "Canada",
        "Bosnia and Herzegovina",
        force=True,
    )
    assert capped.pick == Outcome.HOME and capped.stake == 250_000
    assert capped.requested_pick == Outcome.HOME
    assert capped.requested_stake == 400_000
    assert capped.requested_p_revised == 0.85
    assert capped.engine_adjustment == "stake_cap"
    print("stake-cap adjustment preserves requested and final amounts: PASS")

    prediction_engine.complete = _completion(
        {
            "p_home_revised": 0.60,
            "p_draw_revised": 0.24,
            "p_away_revised": 0.16,
            "pick": "not-an-outcome",
            "stake": 100_000,
            "reasoning": "Malformed requested pick.",
        },
        "gen-invalid",
    )
    invalid = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        1_000_000,
        "Canada",
        "Bosnia and Herzegovina",
        force=True,
    )
    assert invalid.is_pass
    assert invalid.requested_pick is None
    assert invalid.requested_stake == 100_000
    assert invalid.requested_p_revised is None
    assert invalid.has_revised_distribution
    assert invalid.engine_adjustment == "invalid_request"

    prediction_engine.complete = _completion(
        {
            "p_home_revised": 0.60,
            "p_draw_revised": 0.24,
            "p_away_revised": 0.16,
            "pick": "pass",
            "stake": 100_000,
            "reasoning": "Contradictory pass with a positive stake.",
        },
        "gen-inconsistent",
    )
    inconsistent = prediction_engine.bet(
        conn,
        MODEL,
        fixture,
        prediction,
        odds,
        1_000_000,
        "Canada",
        "Bosnia and Herzegovina",
        force=True,
    )
    assert inconsistent.is_pass
    assert inconsistent.requested_stake == 100_000
    assert inconsistent.engine_adjustment == "invalid_request"

    eliminated = prediction_engine._record_pass(
        conn,
        MODEL,
        fixture,
        "eliminated — betting disabled",
        odds,
        force=True,
    )
    assert eliminated.is_pass
    assert eliminated.requested_pick is None
    assert eliminated.requested_stake is None
    assert eliminated.engine_adjustment == "eliminated"
    print("invalid, inconsistent, and eliminated actions are classified: PASS")

    conn.close()
    _verify_human_actions()
    _verify_legacy_migration()


if __name__ == "__main__":
    main()
