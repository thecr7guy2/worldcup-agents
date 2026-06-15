"""Authenticated, read-only "friend" API — match discovery + one models locked bet.

Two GET routes, gated by a shared key (`settings.friend_api_key`; empty key = both routes
404, so the feature stays invisible):

  GET /api/external/matches  — the schedule (fixture_id, date, teams) so a caller whose IDs
                               differ from ours can index a match by DATE + TEAM NAME.
  GET /api/external/bet      — one competitors final pick / stake / reasoning for a match,
                               selected by fixture id OR by date + team.

Our integer fixture ids are locally-minted surrogates (openfootball schedule spine), NOT a
shared/official id, so callers must join on date + team name — hence both routes speak that
language. Read-only; the secret Human Challenger is never addressable (model lookup goes
through `db.list_competitors`, which excludes `is_human`).
"""

from __future__ import annotations

import hmac
import sqlite3
from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, Request

from .. import db
from ..config import settings
from ..models import Fixture

router = APIRouter(prefix="/api/external", tags=["external"])


def _feature_enabled() -> bool:
    """Return whether the friend API has been configured."""
    return bool(settings.friend_api_key)


def require_api_key(request: Request) -> None:
    """404 if the feature is off; 401 unless a valid key arrives via the X-API-Key header
    or a ?key= query param (constant-time compare)."""
    if not _feature_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    sent = request.headers.get("x-api-key") or request.query_params.get("key") or ""
    if not sent or not hmac.compare_digest(sent, settings.friend_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _team_name(conn: sqlite3.Connection, tid: int | None, label: str | None) -> str:
    """Resolve a team id, falling back to its bracket label."""
    if tid is not None:
        t = db.get_team(conn, tid)
        if t:
            return t.name
    return label or "TBD"


def _date_of(fx: Fixture) -> str:
    """UTC calendar date of kickoff (YYYY-MM-DD) — the cross-system join key with team."""
    return fx.kickoff.astimezone(timezone.utc).date().isoformat()


def _fixture_brief(conn: sqlite3.Connection, fx: Fixture) -> dict:
    """Serialize the identifying fields shared by external fixture responses."""
    return {
        "fixture_id": fx.id,
        "date": _date_of(fx),
        "kickoff": fx.kickoff.isoformat(),
        "stage": fx.stage.value,
        "group": fx.group,
        "home": _team_name(conn, fx.home_id, fx.home_label),
        "away": _team_name(conn, fx.away_id, fx.away_label),
        "status": fx.status.value,
    }


def _matches(
    conn: sqlite3.Connection, *, date: str | None, team: str | None, stage: str | None
) -> list[tuple[Fixture, dict]]:
    """Fixtures filtered by UTC date / team-name substring / stage (any combination)."""
    t = team.strip().lower() if team else None
    out = []
    for fx in db.list_fixtures(conn):
        brief = _fixture_brief(conn, fx)
        if date and brief["date"] != date:
            continue
        if stage and brief["stage"] != stage:
            continue
        if t and t not in brief["home"].lower() and t not in brief["away"].lower():
            continue
        out.append((fx, brief))
    out.sort(key=lambda fb: fb[0].kickoff)
    return out


@router.get("/matches")
def list_matches(
    request: Request,
    date: str | None = Query(default=None, description="UTC date YYYY-MM-DD"),
    team: str | None = Query(
        default=None, description="team name (substring, case-insensitive)"
    ),
    stage: str | None = Query(default=None, description="group | round_of_32 | ..."),
) -> dict:
    """The schedule so a caller can find a match by date + team and read off its fixture_id."""
    require_api_key(request)
    conn = db.connect()
    try:
        rows = []
        for fx, brief in _matches(conn, date=date, team=team, stage=stage):
            n_bets = conn.execute(
                "SELECT COUNT(*) FROM bet b JOIN competitor c ON c.model_name = b.model_name "
                "WHERE b.fixture_id = ? AND c.is_human = 0",
                (fx.id,),
            ).fetchone()[0]
            brief["bets_available"] = n_bets > 0
            rows.append(brief)
        return {"count": len(rows), "matches": rows}
    finally:
        conn.close()


def _resolve_fixture(
    conn: sqlite3.Connection, fixture: int | None, date: str | None, team: str | None
) -> Fixture:
    """Pick exactly one fixture from an id, or from date+team. Ambiguity is a 409 that lists
    the candidates so the caller can narrow with a date or the explicit fixture_id."""
    if fixture is not None:
        fx = db.get_fixture(conn, fixture)
        if fx is None:
            raise HTTPException(status_code=404, detail=f"No fixture {fixture}")
        return fx
    if not date and not team:
        raise HTTPException(
            status_code=400,
            detail="Provide fixture, or date and/or team, to identify a match.",
        )
    cands = _matches(conn, date=date, team=team, stage=None)
    if not cands:
        raise HTTPException(
            status_code=404, detail="No match found for those date/team filters."
        )
    if len(cands) > 1:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Multiple matches — narrow with a date (and team).",
                "candidates": [b for _, b in cands],
            },
        )
    return cands[0][0]


@router.get("/bet")
def model_bet(
    request: Request,
    model: str = Query(
        ..., description="competitor / LLM display name (case-insensitive)"
    ),
    fixture: int | None = Query(default=None, description="our fixture id (optional)"),
    date: str | None = Query(default=None, description="UTC date YYYY-MM-DD"),
    team: str | None = Query(
        default=None, description="a team in the match (substring)"
    ),
) -> dict:
    """One models final bet: pick, stake, reasoning, plus date + teams so the match is
    identifiable without our internal id. Select by fixture id, by date+team, or omit all
    to get the models most recent bet."""
    require_api_key(request)
    conn = db.connect()
    try:
        comp = next(
            (
                c
                for c in db.list_competitors(conn)
                if c.model_name.lower() == model.strip().lower()
            ),
            None,
        )
        if comp is None:
            raise HTTPException(status_code=404, detail=f"Unknown model {model!r}")
        name = comp.model_name

        if fixture is None and not date and not team:
            # No selector: the models most recent bet (bets lock ~50 min pre-kickoff in
            # kickoff order, so the newest is the nearest match).
            row = conn.execute(
                "SELECT fixture_id FROM bet WHERE model_name = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (name,),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404, detail=f"{name} has not placed any bets yet"
                )
            fx = db.get_fixture(conn, row["fixture_id"])
        else:
            fx = _resolve_fixture(conn, fixture, date, team)

        bet = db.get_bet(conn, name, fx.id)
        if bet is None:
            raise HTTPException(
                status_code=404,
                detail=f"{name} has no bet on {_date_of(fx)} "
                f"{_team_name(conn, fx.home_id, fx.home_label)} vs "
                f"{_team_name(conn, fx.away_id, fx.away_label)} (bets lock ~50 min pre-kickoff).",
            )
        pred = db.get_prediction(conn, name, fx.id)
        brief = _fixture_brief(conn, fx)
        return {
            "model": name,
            **brief,
            "match": f'{brief["home"]} vs {brief["away"]}',
            "predicted_winner": pred.winner.value if pred else None,
            "confidence": pred.confidence if pred else None,
            "pick": bet.pick.value if bet.pick else "pass",
            "stake": bet.stake,
            "odds_at_bet": bet.odds_at_bet,
            "revised_probabilities": {
                "home": bet.p_home_revised,
                "draw": bet.p_draw_revised,
                "away": bet.p_away_revised,
            },
            "requested_pick": (
                bet.requested_pick.value if bet.requested_pick else "pass"
            ),
            "requested_stake": bet.requested_stake,
            "engine_adjustment": bet.engine_adjustment,
            "reasoning": bet.reasoning,
        }
    finally:
        conn.close()


# A canned sample in the EXACT shape of a /bet response, so a caller can build and test
# their parser before any real bet exists (bets lock ~50 min pre-kickoff). Clearly flagged
# example=True and served from a constant — it touches no competition data.
_EXAMPLE_BET = {
    "example": True,
    "note": "Sample only — identical shape to GET /api/external/bet. Not a real bet.",
    "model": "MiniMax-M3",
    "fixture_id": 9999,
    "date": "2026-06-11",
    "kickoff": "2026-06-11T19:00:00+00:00",
    "stage": "group",
    "group": "C",
    "home": "Brazil",
    "away": "Morocco",
    "status": "scheduled",
    "match": "Brazil vs Morocco",
    "predicted_winner": "home",
    "confidence": 0.58,
    "pick": "home",
    "stake": 200000.0,
    "odds_at_bet": 1.72,
    "revised_probabilities": {"home": None, "draw": None, "away": None},
    "requested_pick": "home",
    "requested_stake": 200000.0,
    "engine_adjustment": None,
    "reasoning": (
        "Brazil's midfield control and stronger attacking depth make the home win my clear "
        "football call. The price is short but still acceptable for a high-conviction 20% tier."
    ),
}


@router.get("/example")
def example(request: Request) -> dict:
    """Return a canned sample bet (same shape as /bet) for integration/parser testing."""
    require_api_key(request)
    return dict(_EXAMPLE_BET)
