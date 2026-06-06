"""The Odds API adapter — fetch 1X2 odds and convert to OddsSnapshot objects.

D5 policy: compute the median of all bookmakers' h2h decimals per event →
one OddsSnapshot(bookmaker="consensus") per event. Skip events with no
bookmakers (log warning). Fail loud on any unmatched team name.
"""

from __future__ import annotations

import logging
import statistics
import time
from datetime import datetime, timezone

import httpx

from ..config import settings
from ..models import Fixture, OddsSnapshot
from .names import normalize

log = logging.getLogger(__name__)

_BASE = "https://api.the-odds-api.com/v4"
_SPORT = "soccer_fifa_world_cup"
_RETRY_STATUS = {429, 500, 502, 503, 504}


def fetch_odds(max_retries: int = 3, backoff: float = 3.0) -> list[dict]:
    """Fetch all current events + odds from The Odds API.

    Returns the raw list of event dicts. Logs remaining quota from headers.
    Raises RuntimeError on non-200 or transport failure.
    """
    if not settings.odds_api_key:
        raise RuntimeError("ODDS_API_KEY is not set")

    url = f"{_BASE}/sports/{_SPORT}/odds"
    params = {
        "apiKey": settings.odds_api_key,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal",
    }

    last_err = ""
    resp = None
    for attempt in range(max_retries + 1):
        try:
            resp = httpx.get(url, params=params, timeout=30.0)
        except httpx.HTTPError as e:
            last_err = str(e)
            if attempt < max_retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise RuntimeError(f"Odds API fetch failed: {last_err}") from e

        if resp.status_code in _RETRY_STATUS and attempt < max_retries:
            time.sleep(backoff * (attempt + 1))
            continue
        break

    if resp is None or resp.status_code != 200:
        status = resp.status_code if resp is not None else "N/A"
        body = resp.text[:300] if resp is not None else last_err
        raise RuntimeError(f"Odds API HTTP {status}: {body}")

    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")
    log.info("Odds API quota: %s remaining, %s used this month", remaining, used)

    return resp.json()


def to_snapshots(events: list[dict], fixtures: list[Fixture]) -> list[OddsSnapshot]:
    """Convert raw Odds API events to consensus OddsSnapshot objects.

    Matches each event to a fixture by normalized home/away names + date.
    Raises RuntimeError listing all unmatched event names (AC#6 — never silent).
    """
    from .names import CANONICAL_TEAMS, team_id_for

    id_to_name = {team_id_for(n): n for n in CANONICAL_TEAMS}

    # Build lookup: (normalized_home, normalized_away, date_str) -> fixture
    fixture_lookup: dict[tuple[str, str, str], Fixture] = {}
    for fx in fixtures:
        if fx.home_id is None or fx.away_id is None:
            continue  # knockout placeholders — no odds posted yet
        home_name = id_to_name.get(fx.home_id, "")
        away_name = id_to_name.get(fx.away_id, "")
        date_str = fx.kickoff.strftime("%Y-%m-%d")
        if home_name and away_name:
            fixture_lookup[(home_name, away_name, date_str)] = fx

    snapshots: list[OddsSnapshot] = []
    unmatched: list[str] = []
    captured_at = datetime.now(timezone.utc)

    for event in events:
        raw_home = event.get("home_team", "")
        raw_away = event.get("away_team", "")
        commence = event.get("commence_time", "")
        date_str = commence[:10] if commence else ""

        try:
            home_name = normalize(raw_home)
            away_name = normalize(raw_away)
        except ValueError as e:
            unmatched.append(str(e))
            continue

        fx = fixture_lookup.get((home_name, away_name, date_str))
        if fx is None:
            unmatched.append(
                f"No fixture match for {home_name!r} vs {away_name!r} on {date_str!r}"
            )
            continue

        bookmakers = event.get("bookmakers", [])
        if not bookmakers:
            log.warning("Event %s has no bookmakers — skipping", event.get("id"))
            continue

        home_prices: list[float] = []
        draw_prices: list[float] = []
        away_prices: list[float] = []

        for bm in bookmakers:
            for market in bm.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    price = float(outcome.get("price", 0))
                    if name == raw_home:
                        home_prices.append(price)
                    elif name == raw_away:
                        away_prices.append(price)
                    elif name == "Draw":
                        draw_prices.append(price)

        if not home_prices or not draw_prices or not away_prices:
            log.warning("Event %s missing price sides — skipping", event.get("id"))
            continue

        snapshots.append(
            OddsSnapshot(
                fixture_id=fx.id,
                captured_at=captured_at,
                bookmaker="consensus",
                home=statistics.median(home_prices),
                draw=statistics.median(draw_prices),
                away=statistics.median(away_prices),
            )
        )

    if unmatched:
        raise RuntimeError(
            f"{len(unmatched)} Odds API event(s) could not be matched to fixtures:\n"
            + "\n".join(f"  - {u}" for u in unmatched)
        )

    return snapshots
