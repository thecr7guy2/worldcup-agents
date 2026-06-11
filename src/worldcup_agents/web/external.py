"""Authenticated, read-only "friend" endpoint — one models locked bet on a match.

A single GET route, gated by a shared API key (`settings.friend_api_key`). An empty key
disables the feature entirely (the route 404s, so it stays invisible), mirroring the
challenger. It returns ONLY a competitors final bet — pick, stake, reasoning (plus the
match and the step-1 prediction for context) — for a given fixture, or the models most
recent bet when no fixture is supplied.

Read-only: it cannot write anything. The secret Human Challenger is never addressable here
because model lookup goes through `db.list_competitors`, which excludes `is_human` rows.
"""

from __future__ import annotations

import hmac
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request

from .. import db
from ..config import settings

router = APIRouter(prefix="/api/external", tags=["external"])


def _feature_enabled() -> bool:
    """The endpoint exists only when an API key is configured."""
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
    if tid is not None:
        t = db.get_team(conn, tid)
        if t:
            return t.name
    return label or "TBD"


@router.get("/bet")
def model_bet(
    request: Request,
    model: str = Query(..., description="competitor / LLM display name (case-insensitive)"),
    fixture: int | None = Query(
        default=None, description="fixture id; omit for the models most recent bet"
    ),
) -> dict:
    """Return one models final bet: pick, stake, reasoning (+ match and step-1 prediction)."""
    require_api_key(request)
    conn = db.connect()
    try:
        # Resolve the model case-insensitively. list_competitors excludes the secret human,
        # so the Human Challenger can never be addressed through this endpoint.
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

        if fixture is not None:
            fixture_id = fixture
            bet = db.get_bet(conn, name, fixture_id)
            if bet is None:
                raise HTTPException(
                    status_code=404, detail=f"No bet from {name} on fixture {fixture_id}"
                )
        else:
            # Bets lock ~50 min before kickoff and are placed in kickoff order, so the most
            # recently created bet is this models pick for the nearest match.
            row = conn.execute(
                "SELECT fixture_id FROM bet WHERE model_name = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (name,),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404, detail=f"{name} has not placed any bets yet"
                )
            fixture_id = row["fixture_id"]
            bet = db.get_bet(conn, name, fixture_id)

        fx = db.get_fixture(conn, fixture_id)
        pred = db.get_prediction(conn, name, fixture_id)
        match = (
            f"{_team_name(conn, fx.home_id, fx.home_label)} vs "
            f"{_team_name(conn, fx.away_id, fx.away_label)}"
            if fx
            else None
        )
        return {
            "model": name,
            "fixture_id": fixture_id,
            "match": match,
            "kickoff": fx.kickoff.isoformat() if fx else None,
            "predicted_winner": pred.winner.value if pred else None,
            "confidence": pred.confidence if pred else None,
            "pick": bet.pick.value if bet.pick else "pass",
            "stake": bet.stake,
            "odds_at_bet": bet.odds_at_bet,
            "reasoning": bet.reasoning,
        }
    finally:
        conn.close()
