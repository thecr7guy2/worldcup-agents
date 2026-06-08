"""Orchestrator regression test — synthetic, offline (no LLM/network).

    uv run python scripts/verify_orchestrate.py

Asserts the "what is due now" selectors at a fixed `now`, the dossier-fold marker, and
that a tick on an all-future DB is a true no-op (zero actions, zero model_call rows) —
proving nothing fires before its window and the tick never calls an LLM when idle.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worldcup_agents import db, orchestrate
from worldcup_agents.config import PREDICTION_MODELS
from worldcup_agents.models import (
    Bet,
    Fixture,
    MatchBriefing,
    MatchStatus,
    OddsSnapshot,
    Outcome,
    Stage,
    Team,
)

NOW = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)


def _fx(
    conn, fid, *, hours_from_now=None, kickoff=None, status=MatchStatus.SCHEDULED, **kw
):
    ko = kickoff or (NOW + timedelta(hours=hours_from_now))
    db.upsert_fixture(
        conn,
        Fixture(
            id=fid,
            stage=kw.pop("stage", Stage.GROUP),
            kickoff=ko,
            home_id=1,
            away_id=2,
            status=status,
            **kw,
        ),
    )


def main() -> None:
    tmp = Path(tempfile.mkdtemp()) / "wc_orch.db"
    conn = db.connect(tmp)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Mexico"))
    db.upsert_team(conn, Team(id=2, name="South Africa"))

    # 600 brief-window (no briefing yet); 601 bet-window (briefing + odds); 602 result-due;
    # 603 in-progress (kicked off, before result delay); 605 far future;
    # 606 bet-window but NO odds; 604 FINISHED on a unique past date.
    _fx(conn, 600, hours_from_now=10)
    _fx(conn, 601, hours_from_now=1)
    _fx(conn, 602, hours_from_now=-3)
    _fx(conn, 603, hours_from_now=-1)
    _fx(conn, 605, hours_from_now=48)
    _fx(conn, 606, hours_from_now=1)
    _fx(
        conn,
        604,
        kickoff=datetime(2026, 6, 18, 19, 0, tzinfo=timezone.utc),
        status=MatchStatus.FINISHED,
        home_goals_90=2,
        away_goals_90=1,
    )

    # Briefings + odds so 601 qualifies for betting; 606 gets a briefing but no odds.
    for fid in (601, 606):
        db.upsert_match_briefing(
            conn, MatchBriefing(fixture_id=fid, created_at=NOW, content="briefing")
        )
    db.upsert_odds_snapshot(
        conn,
        OddsSnapshot(
            fixture_id=601,
            captured_at=NOW,
            bookmaker="consensus",
            home=2.0,
            draw=3.2,
            away=3.8,
        ),
    )

    fixtures = db.list_fixtures(conn)

    # --- Selectors ---
    assert {f.id for f in orchestrate.due_for_result(fixtures, NOW)} == {602}, "result"
    assert {f.id for f in orchestrate.due_for_brief(conn, fixtures, NOW)} == {
        600
    }, "brief"  # 601/606 already briefed; 605 too far; 603 kicked off
    assert {f.id for f in orchestrate.due_for_bet(conn, fixtures, NOW)} == {
        601
    }, "bet"  # 606 excluded (no odds); 600 too early
    print("selectors (result / brief / bet incl. odds + window gating): PASS")

    # --- Settle selector: a finished fixture with an unsettled bet ---
    db.upsert_bet(
        conn,
        Bet(
            model_name=PREDICTION_MODELS[0].name,
            fixture_id=604,
            pick=Outcome.HOME,
            stake=1000.0,
            odds_at_bet=2.0,
            created_at=NOW,
        ),
    )
    # 604 is the only fixture on 2026-06-18, so that matchday is fully resolved and due.
    fixtures = db.list_fixtures(conn)
    assert "2026-06-18" in orchestrate.due_matchdays_to_settle(conn, fixtures)
    from worldcup_agents import settlement

    settlement.settle_matchday(conn, "2026-06-18")
    assert "2026-06-18" not in orchestrate.due_matchdays_to_settle(conn, fixtures)
    print("settle selector (matchday unsettled -> settled excluded): PASS")

    # --- Post-process selector + dossier-fold marker ---
    assert 604 in {f.id for f in orchestrate.due_for_postprocess(conn, fixtures)}
    assert not db.dossier_folded(conn, 604, 1)
    db.mark_dossier_folded(conn, 604, 1, NOW.isoformat())
    db.mark_dossier_folded(conn, 604, 2, NOW.isoformat())
    assert db.dossier_folded(conn, 604, 1) and db.dossier_folded(conn, 604, 2)
    assert 604 not in {f.id for f in orchestrate.due_for_postprocess(conn, fixtures)}
    print("postprocess selector + dossier-fold marker: PASS")

    # --- Decay selector: only the fully-closed, not-yet-decayed day (2026-06-18) ---
    assert orchestrate.due_matchdays(conn, fixtures) == ["2026-06-18"]
    print("decay selector (only fully-closed undecayed matchdays): PASS")

    # --- Tick on an all-future DB is a true no-op: zero actions, ZERO model_call rows ---
    tmp2 = Path(tempfile.mkdtemp()) / "wc_orch_idle.db"
    c2 = db.connect(tmp2)
    db.init_db(c2)
    db.upsert_team(c2, Team(id=1, name="Mexico"))
    db.upsert_team(c2, Team(id=2, name="South Africa"))
    _fx(c2, 700, hours_from_now=72)  # beyond every window
    s = orchestrate.tick(c2, now=NOW)
    assert s == orchestrate._new_summary(), s  # all zeros, no errors
    calls = c2.execute("SELECT COUNT(*) FROM model_call").fetchone()[0]
    assert calls == 0, f"expected no LLM calls on an idle tick, got {calls}"
    print("idle tick is a no-op (no actions, no LLM calls): PASS")

    print("\nALL ACCEPTANCE CRITERIA PASS")


if __name__ == "__main__":
    main()
