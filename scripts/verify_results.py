"""Result-ingestion regression test — synthetic, no network for the core logic.

    uv run python scripts/verify_results.py

Drives the settlement-critical parse/validate/write path (`_parse_result` +
`_apply_parsed`) across every result shape, plus `ingest_result`'s offline temporal
guards (which return before any LLM call) and an `extract_json` equivalence check.
The live web-search integration reuses the proven OpenRouter `web` path; 2026 results
don't exist yet (opener is 2026-06-11), so it isn't asserted here.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from worldcup_agents import db
from worldcup_agents.llm import LLMError, extract_json
from worldcup_agents.models import Fixture, MatchStatus, Outcome, Stage, Team
from worldcup_agents.results import _apply_parsed, _parse_result, ingest_result


def _fx(conn, fid, stage, kickoff):
    db.upsert_fixture(
        conn,
        Fixture(id=fid, stage=stage, kickoff=kickoff, home_id=1, away_id=2),
    )
    return db.get_fixture(conn, fid)


def expect_error(fn, label):
    try:
        fn()
    except LLMError:
        return
    raise AssertionError(f"expected LLMError: {label}")


def main() -> None:
    tmp = Path(tempfile.mkdtemp()) / "wc_results.db"
    conn = db.connect(tmp)
    db.init_db(conn)
    db.upsert_team(conn, Team(id=1, name="Mexico"))
    db.upsert_team(conn, Team(id=2, name="South Africa"))
    past = datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc)

    # AC1 finished group 2-1 → FINISHED, result_90 HOME, advanced None.
    g = _fx(conn, 700, Stage.GROUP, past)
    p = _parse_result({"status": "finished", "home_goals_90": 2, "away_goals_90": 1}, g)
    assert p["advanced_id"] is None and p["went_penalties"] is False
    fx = _apply_parsed(conn, g, p)
    assert fx.status == MatchStatus.FINISHED and fx.result_90() is Outcome.HOME

    # AC2 knockout decisive 2-1 → advanced derived = home (id 1).
    k = _fx(conn, 701, Stage.R16, past)
    p = _parse_result({"status": "finished", "home_goals_90": 2, "away_goals_90": 1}, k)
    assert p["advanced_id"] == 1, p
    assert _apply_parsed(conn, k, p).result_90() is Outcome.HOME

    # AC3 knockout 1-1, pens, advanced=away → goals level, pens True, advanced id 2,
    # result_90 DRAW (so a 'home'/'away' 1X2 bet would LOSE downstream).
    kp = _fx(conn, 702, Stage.R16, past)
    p = _parse_result(
        {
            "status": "finished",
            "home_goals_90": 1,
            "away_goals_90": 1,
            "went_penalties": True,
            "advanced": "away",
        },
        kp,
    )
    assert p["went_penalties"] and p["advanced_id"] == 2, p
    fx = _apply_parsed(conn, kp, p)
    assert fx.result_90() is Outcome.DRAW and fx.went_penalties is True

    # AC4 ET/pens but a non-level 90' score → integrity reject.
    expect_error(
        lambda: _parse_result(
            {
                "status": "finished",
                "home_goals_90": 2,
                "away_goals_90": 1,
                "went_penalties": True,
            },
            k,
        ),
        "pens with non-level 90'",
    )

    # AC5 not_finished → nothing written.
    nf = _fx(conn, 703, Stage.GROUP, past)
    p = _parse_result({"status": "not_finished"}, nf)
    assert _apply_parsed(conn, nf, p) is None
    assert db.get_fixture(conn, 703).status == MatchStatus.SCHEDULED

    # AC6 postponed → POSTPONED.
    pp = _fx(conn, 704, Stage.GROUP, past)
    p = _parse_result({"status": "postponed"}, pp)
    assert _apply_parsed(conn, pp, p).status == MatchStatus.POSTPONED

    # AC7 invalid status / missing / negative goals → reject.
    expect_error(lambda: _parse_result({"status": "??"}, g), "bad status")
    expect_error(
        lambda: _parse_result({"status": "finished", "home_goals_90": 1}, g),
        "missing away goals",
    )
    expect_error(
        lambda: _parse_result(
            {"status": "finished", "home_goals_90": -1, "away_goals_90": 0}, g
        ),
        "negative goals",
    )
    print("parse/apply: group / knockout / pens-draw / integrity / void / errors: PASS")

    # AC8 temporal guards — these return BEFORE any web search (offline-safe).
    future = datetime.now(timezone.utc) + timedelta(days=3)
    _fx(conn, 705, Stage.GROUP, future)
    assert ingest_result(conn, 705) is None  # not kicked off → no search
    # already resolved → returns it without searching
    done = _fx(conn, 706, Stage.GROUP, past)
    _apply_parsed(
        conn,
        done,
        _parse_result(
            {"status": "finished", "home_goals_90": 0, "away_goals_90": 0}, done
        ),
    )
    got = ingest_result(conn, 706)
    assert got is not None and got.status == MatchStatus.FINISHED
    print("ingest_result guards (pre-kickoff skip / idempotent resolved): PASS")

    # AC9 extract_json behaves like the old predict._extract_json.
    assert extract_json('```json\n{"a": 1, "b": "x"}\n```')["a"] == 1
    assert extract_json('noise {"k": {"n": 2}} trailing')["k"]["n"] == 2
    expect_error(lambda: extract_json("no json here"), "no object")
    print("extract_json equivalence: PASS")

    print("\nALL ACCEPTANCE CRITERIA PASS")


if __name__ == "__main__":
    main()
