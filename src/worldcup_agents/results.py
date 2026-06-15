"""Result ingestion — the intelligence agent web-searches concluded match results.

Replaces the manual `settlement result` command for the live tournament. Per the
data lineage (DESIGN §3; tasks/todo.md §6), results come from the intelligence
agent's web search, NOT a score API: only a researched source reliably gives the
90-minute / extra-time / penalties split that 1X2 settlement needs (a knockout
1-1 won on penalties must settle as a DRAW on the 90' score — DESIGN §7).

Temporal integrity (DESIGN §4): a result is ingested only AFTER kickoff and only
when a reliable source confirms the match concluded — otherwise nothing is written
(never fabricate). The structured result is handed to settlement.record_result,
the single writer of fixture outcomes.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone

from . import db
from .config import INTELLIGENCE_MODEL, RESULT_CONFIRM_READS, ModelSpec
from .llm import LLMError, complete, extract_json
from .models import Fixture, MatchStatus, Stage
from .settlement import record_result

SYSTEM_RESULTS = """You are a meticulous football results researcher. You report ONLY \
verified, concluded match facts from reputable sources (official FIFA, major sports \
outlets). You never guess, infer, or report a result you cannot confirm — if in doubt, \
you say the match is not finished."""


def _now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _team_name(conn: sqlite3.Connection, team_id: int | None, label: str | None) -> str:
    """Resolve a team id, falling back to an unresolved bracket label."""
    if team_id is not None:
        team = db.get_team(conn, team_id)
        if team:
            return team.name
    return label or "?"


def _build_prompt(home: str, away: str, fixture: Fixture) -> str:
    """Build the strict result-research prompt for one fixture."""
    venue = f" at {fixture.venue}" if fixture.venue else ""
    return f"""Match: {home} (home) vs {away} (away) — FIFA World Cup 2026, \
{fixture.stage.value}, kicked off {fixture.kickoff.isoformat()} (UTC){venue}.

Using web search, find the OFFICIAL result of THIS specific match. I need the score at \
the end of NORMAL TIME (90 minutes + stoppage), NOT including extra time or penalties.

Respond with ONLY a JSON object, no other text:
{{"status": "finished" | "not_finished" | "postponed",
  "home_goals_90": <int ≥ 0 or null>,
  "away_goals_90": <int ≥ 0 or null>,
  "went_extra_time": <true|false>,
  "went_penalties": <true|false>,
  "advanced": "home" | "away" | null,
  "source": "<source name + date>"}}

Rules:
- home_goals_90 / away_goals_90 are {home}'s and {away}'s goals after 90 minutes of \
regulation only.
- If the match has not kicked off, is still in progress, or you cannot verify a final \
result from a reliable source: status="not_finished", goals null. Do NOT guess.
- Knockout matches that went to extra time / penalties: report the 90-MINUTE regulation \
score (a draw), set went_extra_time / went_penalties accordingly, and set "advanced" to \
the team that ultimately progressed (penalties count for advancing, NOT for the 90' score).
- Group-stage matches: "advanced" must be null.
- Postponed or abandoned: status="postponed"."""


def _parse_result(data: dict, fixture: Fixture) -> dict:
    """Validate + normalize the model's JSON into fixture-result fields. Pure; raises
    LLMError on anything garbled (fail loud — a bad 90' score corrupts settlement)."""
    status = str(data.get("status", "")).strip().lower()
    if status not in {"finished", "not_finished", "postponed"}:
        raise LLMError(f"invalid status in result {data!r}")

    if status != "finished":
        return {
            "status": status,
            "home_goals_90": None,
            "away_goals_90": None,
            "went_extra_time": False,
            "went_penalties": False,
            "advanced_id": None,
        }

    try:
        hg = int(data["home_goals_90"])
        ag = int(data["away_goals_90"])
    except (KeyError, ValueError, TypeError):
        raise LLMError(f"invalid/missing 90' goals in finished result {data!r}")
    if hg < 0 or ag < 0:
        raise LLMError(f"negative goals in {data!r}")

    et = bool(data.get("went_extra_time"))
    pens = bool(data.get("went_penalties"))
    # Integrity: ET/penalties only happen from a level game at 90'.
    if (et or pens) and hg != ag:
        raise LLMError(
            f"extra-time/penalties but 90' score is not level ({hg}-{ag}): {data!r}"
        )

    advanced_id = _resolve_advanced(data.get("advanced"), fixture, hg, ag)
    return {
        "status": status,
        "home_goals_90": hg,
        "away_goals_90": ag,
        "went_extra_time": et,
        "went_penalties": pens,
        "advanced_id": advanced_id,
    }


def _resolve_advanced(
    advanced: object, fixture: Fixture, hg: int, ag: int
) -> int | None:
    """Map who progressed to a team id. Group → None. Knockout decided in 90' → the
    90' winner (derived). Knockout level at 90' → the side the model reports."""
    if fixture.stage == Stage.GROUP:
        return None
    if hg != ag:  # decisive in regulation — the winner advances
        return fixture.home_id if hg > ag else fixture.away_id
    side = str(advanced).strip().lower() if advanced is not None else ""
    if side == "home":
        return fixture.home_id
    if side == "away":
        return fixture.away_id
    return None  # level at 90' but advancer unreported — leave unresolved


def _apply_parsed(
    conn: sqlite3.Connection, fixture: Fixture, parsed: dict
) -> Fixture | None:
    """Write a parsed result via the single result-writer. Returns the updated fixture,
    or None for not_finished (nothing recorded)."""
    if parsed["status"] == "not_finished":
        return None
    if parsed["status"] == "postponed":
        return record_result(conn, fixture.id, None, None, postponed=True)
    return record_result(
        conn,
        fixture.id,
        parsed["home_goals_90"],
        parsed["away_goals_90"],
        extra_time=parsed["went_extra_time"],
        penalties=parsed["went_penalties"],
        advanced_id=parsed["advanced_id"],
    )


def ingest_result(
    conn: sqlite3.Connection,
    fixture_id: int,
    *,
    model: ModelSpec = INTELLIGENCE_MODEL,
    force: bool = False,
) -> Fixture | None:
    """Web-search and record one fixture's concluded result. Returns the updated fixture
    when a result (finished/postponed) is written, else None. Idempotent and temporally
    guarded — it does not search before kickoff or for an already-resolved fixture."""
    fixture = db.get_fixture(conn, fixture_id)
    if fixture is None:
        raise ValueError(f"no fixture with id {fixture_id}")
    if not force and fixture.status in (MatchStatus.FINISHED, MatchStatus.POSTPONED):
        return fixture  # already resolved — no wasted search
    if _now() < fixture.kickoff:
        return None  # cannot have a result before kickoff

    home = _team_name(conn, fixture.home_id, fixture.home_label)
    away = _team_name(conn, fixture.away_id, fixture.away_label)

    def _one_read() -> dict:
        """Perform and validate one independent result-research call."""
        text, call = complete(
            model.model_id,
            _build_prompt(home, away, fixture),
            model_name=model.name,
            step="result",
            fixture_id=fixture.id,
            system=SYSTEM_RESULTS,
            max_tokens=3000,  # headroom for reasoning models (tokens spent thinking)
            temperature=0.0,  # factual extraction — deterministic
            web_search=True,
        )
        db.log_model_call(conn, call)
        return _parse_result(extract_json(text), fixture)

    parsed = _one_read()
    if parsed["status"] == "not_finished":
        return None  # nothing to write — no need to spend a confirming search

    # A wrong score here corrupts settlement AND both dossiers irreversibly, and a
    # web-searching LLM can mis-read a live/partial score page. So before WRITING a
    # result, require a second independent read (fresh search) to return the identical
    # parsed result. Disagreement aborts the write — fail loud, retry next tick.
    if RESULT_CONFIRM_READS > 1:
        for _ in range(RESULT_CONFIRM_READS - 1):
            confirm = _one_read()
            if confirm != parsed:
                raise LLMError(
                    f"result reads disagree for fixture {fixture.id} "
                    f"({home} vs {away}): {parsed!r} vs {confirm!r} — "
                    "not recording; will retry next tick"
                )

    return _apply_parsed(conn, fixture, parsed)


# ---- CLI -----------------------------------------------------------------


def _describe(conn: sqlite3.Connection, fx: Fixture) -> str:
    """Render a concise human-readable fixture result."""
    home = _team_name(conn, fx.home_id, fx.home_label)
    away = _team_name(conn, fx.away_id, fx.away_label)
    if fx.status == MatchStatus.POSTPONED:
        return f"{home} vs {away} — POSTPONED"
    if fx.result_90() is not None:
        extra = []
        if fx.went_extra_time:
            extra.append("a.e.t.")
        if fx.went_penalties:
            extra.append("pens")
        tag = f" ({', '.join(extra)})" if extra else ""
        return (
            f"{home} {fx.home_goals_90}-{fx.away_goals_90} {away}{tag} "
            f"→ 90' = {fx.result_90().value}"
        )
    return f"{home} vs {away} — no result"


def _cmd_ingest(args: argparse.Namespace) -> None:
    """Research and record the result for one requested fixture."""
    conn = db.connect()
    db.init_db(conn)
    fx = ingest_result(conn, args.fixture_id, force=args.force)
    if fx is None:
        print(
            f"Fixture {args.fixture_id}: no result recorded (not finished / not due)."
        )
    else:
        print(f"Fixture {args.fixture_id}: {_describe(conn, fx)}")


def _cmd_due(args: argparse.Namespace) -> None:
    """Research every kicked-off fixture that remains unresolved."""
    conn = db.connect()
    db.init_db(conn)
    now = _now()
    due = [
        f
        for f in db.list_fixtures(conn)
        if f.kickoff <= now
        and f.status not in (MatchStatus.FINISHED, MatchStatus.POSTPONED)
    ]
    if not due:
        print("No kicked-off, unresolved fixtures.")
        return
    print(f"Ingesting results for {len(due)} kicked-off fixture(s)...\n")
    recorded = 0
    for f in due:
        fx = ingest_result(conn, f.id, force=args.force)
        if fx is None:
            print(f"  fixture {f.id}: still not finished")
        else:
            print(f"  fixture {f.id}: {_describe(conn, fx)}")
            recorded += 1
    print(f"\nRecorded {recorded} / {len(due)} results.")


def main() -> None:
    """Parse and dispatch the result-ingestion command-line interface."""
    parser = argparse.ArgumentParser(prog="worldcup_agents.results")
    sub = parser.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("ingest", help="web-search + record one fixture's result")
    i.add_argument("fixture_id", type=int)
    i.add_argument("--force", action="store_true", help="re-fetch even if resolved")
    i.set_defaults(func=_cmd_ingest)

    d = sub.add_parser("due", help="ingest every kicked-off, unresolved fixture")
    d.add_argument("--force", action="store_true", help="re-fetch even if resolved")
    d.set_defaults(func=_cmd_due)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
