"""FastAPI JSON API over the live competition DB (read-only).

Run (dev):  uv run uvicorn worldcup_agents.web.app:app --reload --port 8001
The Next.js frontend proxies /api/* to this process, so the browser sees one origin.
Set WORLDCUP_DB to point at the live database; defaults to ./worldcup.db.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..db import DEFAULT_DB_PATH
from . import stats

app = FastAPI(title="LLM World Cup — The Arena", version="1.0")

# Dev convenience: the Next dev server may call the API cross-origin before the
# rewrite proxy is wired. Read-only API, so a permissive policy is harmless.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_conn() -> sqlite3.Connection:
    """Open the competition DB strictly read-only (one connection per request)."""
    conn = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/overview")
def api_overview() -> dict:
    conn = get_conn()
    try:
        return stats.overview(conn)
    finally:
        conn.close()


@app.get("/api/competitors")
def api_competitors() -> list[dict]:
    conn = get_conn()
    try:
        return stats.list_competitors(conn)
    finally:
        conn.close()


@app.get("/api/competitors/{name}")
def api_competitor(name: str) -> dict:
    conn = get_conn()
    try:
        card = stats.competitor_detail(conn, name)
        if card is None:
            raise HTTPException(status_code=404, detail=f"No competitor named {name!r}")
        return card
    finally:
        conn.close()


@app.get("/api/leaderboard/bankroll")
def api_leaderboard_bankroll() -> list[dict]:
    conn = get_conn()
    try:
        return stats.leaderboard_bankroll(conn)
    finally:
        conn.close()


@app.get("/api/leaderboard/accuracy")
def api_leaderboard_accuracy() -> list[dict]:
    conn = get_conn()
    try:
        return stats.leaderboard_accuracy(conn)
    finally:
        conn.close()


@app.get("/api/fixtures")
def api_fixtures(day: str | None = None, stage: str | None = None) -> list[dict]:
    conn = get_conn()
    try:
        return stats.list_fixtures(conn, day=day, stage=stage)
    finally:
        conn.close()


@app.get("/api/fixtures/{fixture_id}")
def api_fixture(fixture_id: int) -> dict:
    conn = get_conn()
    try:
        detail = stats.fixture_detail(conn, fixture_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"No fixture {fixture_id}")
        return detail
    finally:
        conn.close()


@app.get("/api/today")
def api_today() -> dict:
    conn = get_conn()
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        return {"date": today, "fixtures": stats.list_fixtures(conn, day=today)}
    finally:
        conn.close()


@app.get("/api/telemetry")
def api_telemetry() -> dict:
    conn = get_conn()
    try:
        return stats.telemetry(conn)
    finally:
        conn.close()
