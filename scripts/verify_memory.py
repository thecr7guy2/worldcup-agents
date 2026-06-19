"""Memory/constitution regression — synthetic, offline, no network.

    uv run python scripts/verify_memory.py
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worldcup_agents import db, memory
from worldcup_agents.config import ModelSpec
from worldcup_agents.models import Bet, Fixture, MatchStatus, ModelCall, Outcome, Stage, Team

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
MODEL = ModelSpec("Memory Agent", "test/memory-agent")
OTHER = "Copy Risk Agent"


def _completion(payload: dict):
    """Build a deterministic fake completion for constitution generation."""

    def fake_complete(model_id, prompt, *, model_name, step, fixture_id=None, **_):
        return json.dumps(payload), ModelCall(
            model_name=model_name,
            step=step,
            fixture_id=fixture_id,
            generation_id="memory-gen",
            prompt_text=prompt,
            response_text=json.dumps(payload),
            created_at=NOW,
        )

    return fake_complete


def main() -> None:
    """Run memory checks."""
    conn = db.connect(Path(tempfile.mkdtemp()) / "memory.db")
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Mexico", group="A"))
    db.upsert_team(conn, Team(id=2, name="South Korea", group="A"))
    db.upsert_fixture(
        conn,
        Fixture(
            id=700,
            stage=Stage.GROUP,
            group="A",
            kickoff=NOW - timedelta(days=1),
            home_id=1,
            away_id=2,
            status=MatchStatus.FINISHED,
            home_goals_90=1,
            away_goals_90=0,
        ),
    )
    db.upsert_fixture(
        conn,
        Fixture(
            id=701,
            stage=Stage.GROUP,
            group="A",
            kickoff=NOW + timedelta(hours=5),
            home_id=1,
            away_id=2,
        ),
    )

    payload = {
        "principles": [
            "Back favorites only when team news supports the price.",
            "Respect draws in tactical stalemates.",
            "Increase risk when the portfolio target is unmet.",
            "Avoid chasing long odds without a football case.",
            "Protect the bankroll after large losses.",
            "Review my own pass rate after every matchday.",
        ],
        "aggression": "medium",
        "favorite_tolerance": "medium",
        "draw_appetite": "high",
        "contrarian_tendency": "low",
        "bankroll_discipline": "high",
        "constitution": "I am a selective bettor who wants real football evidence before risking money.",
    }
    memory.complete = _completion(payload)
    c = memory.ask_constitution(conn, MODEL)
    assert c.draw_appetite == "high"
    assert db.get_agent_constitution(conn, MODEL.name) == c
    assert conn.execute("SELECT COUNT(*) FROM model_call WHERE step='constitution'").fetchone()[0] == 1
    print("constitution generation + storage: PASS")

    fixture = db.get_fixture(conn, 701)
    shared = memory.shared_tournament_memory(conn, fixture)
    assert "Mexico 1-0 South Korea" in shared
    assert "No tournament matches have finished" not in shared
    print("shared tournament memory reads authoritative results: PASS")

    db.upsert_bet(
        conn,
        Bet(
            model_name=MODEL.name,
            fixture_id=700,
            pick=Outcome.HOME,
            stake=100_000,
            odds_at_bet=2.0,
            created_at=NOW,
        ),
    )
    db.upsert_bet(
        conn,
        Bet(
            model_name=OTHER,
            fixture_id=700,
            pick=Outcome.AWAY,
            stake=200_000,
            odds_at_bet=3.0,
            created_at=NOW,
        ),
    )
    private = memory.private_memory_block(conn, MODEL.name)
    assert OTHER not in private
    assert "100,000" in private
    print("private self-memory excludes other agents: PASS")

    bundle = memory.betting_memory_block(conn, MODEL.name, fixture)
    assert "Your Betting Constitution" in bundle
    assert "Your Private Self-Memory" in bundle
    assert "Shared Tournament Memory" in bundle
    print("betting memory bundle: PASS")

    print("\nALL MEMORY CHECKS PASS")


if __name__ == "__main__":
    main()
