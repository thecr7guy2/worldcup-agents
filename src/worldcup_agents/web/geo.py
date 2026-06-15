"""Visitor-geography routes — the public audience widget's write + read surface.

  POST /api/track        — internal ingest. The Next edge (which alone sees the real client
                           IP behind the public proxy) posts {visitor_id, ip, is_challenger}
                           with the shared `track_ingest_key`. We resolve the IP to coarse
                           geography and upsert the visitor. The raw IP is never stored.
  GET  /api/geo/summary  — public rollup: unique visitors, Challengers, per-country counts.

Ingest is gated by `settings.track_ingest_key` (empty = the POST route 404s, so the public
can't seed visits and the feature is simply off). The summary is always public — it exposes
only aggregate geography.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import db
from ..config import settings
from ..sources import geo

router = APIRouter(tags=["geo"])


class TrackBody(BaseModel):
    """Visitor beacon payload forwarded by the trusted Next.js edge route."""

    visitor_id: str
    ip: str | None = None
    is_challenger: bool = False


def _require_ingest_key(request: Request) -> None:
    """404 when ingest is disabled; 401 unless the shared key matches (constant-time)."""
    if not settings.track_ingest_key:
        raise HTTPException(status_code=404, detail="Not found")
    sent = request.headers.get("x-ingest-key") or ""
    if not sent or not hmac.compare_digest(sent, settings.track_ingest_key):
        raise HTTPException(status_code=401, detail="Invalid or missing ingest key")


@router.post("/api/track")
def track(body: TrackBody, request: Request) -> dict:
    """Record (or refresh) one visitor. Geo failures degrade to an 'Unknown' visit."""
    _require_ingest_key(request)
    vid = body.visitor_id.strip()
    if not vid:
        raise HTTPException(status_code=400, detail="visitor_id required")
    g = geo.lookup(body.ip) or {}
    conn = db.connect()
    try:
        db.record_visit(
            conn,
            vid,
            country_code=g.get("country_code"),
            country_name=g.get("country_name"),
            region=g.get("region"),
            is_challenger=body.is_challenger,
        )
    finally:
        conn.close()
    return {"ok": True}


@router.get("/api/geo/summary")
def geo_summary() -> dict:
    """Public audience rollup for the visitor-geography widget. The Challenger-visitor count is
    stored (is_challenger) but stripped here — surfacing it publicly would leak the existence of
    the secret Human Challenger, so it stays off the public surface."""
    conn = db.connect()
    try:
        s = db.visit_summary(conn)
        s.pop("challengers", None)
        return s
    finally:
        conn.close()
