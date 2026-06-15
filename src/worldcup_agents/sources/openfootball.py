"""openfootball schedule adapter.

Fetches the 2026 World Cup schedule JSON, caches it for 24 h, then parses it
into Team and Fixture domain objects. No API key required.

UTC conversion: openfootball times are local with a "UTC±N" suffix.
  "13:00 UTC-6" → 13:00 - (-6h) = 19:00Z.  Verified against Odds-API.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from ..models import Fixture, Stage, Team
from .names import CANONICAL_TEAMS, is_placeholder, normalize, team_id_for

_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
_CACHE_DIR = Path(".cache")
_CACHE_FILE = _CACHE_DIR / "worldcup_2026.json"
_CACHE_TTL = 86_400  # 24 h in seconds

_RETRY_STATUS = {429, 500, 502, 503, 504}

_ROUND_TO_STAGE: dict[str, Stage] = {
    "Round of 32": Stage.R32,
    "Round of 16": Stage.R16,
    "Quarter-final": Stage.QF,
    "Semi-final": Stage.SF,
    "Match for third place": Stage.THIRD,
    "Final": Stage.FINAL,
}


def fetch_schedule() -> dict:
    """Return the raw schedule dict, using a 24-hour disk cache."""
    _CACHE_DIR.mkdir(exist_ok=True)

    if _CACHE_FILE.exists():
        age = time.time() - _CACHE_FILE.stat().st_mtime
        if age < _CACHE_TTL:
            return json.loads(_CACHE_FILE.read_text())

    raw = _http_get(_URL)
    _CACHE_FILE.write_text(json.dumps(raw))
    return raw


def _http_get(url: str, max_retries: int = 3, backoff: float = 3.0) -> dict:
    """Fetch and decode JSON with bounded retries for transient failures."""
    last_err = ""
    for attempt in range(max_retries + 1):
        try:
            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        except httpx.HTTPError as e:
            last_err = str(e)
            if attempt < max_retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise RuntimeError(f"openfootball fetch failed: {last_err}") from e

        if resp.status_code in _RETRY_STATUS and attempt < max_retries:
            time.sleep(backoff * (attempt + 1))
            continue
        if resp.status_code != 200:
            raise RuntimeError(
                f"openfootball HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    raise RuntimeError(f"openfootball fetch failed after retries: {last_err}")


def parse_schedule(raw: dict) -> tuple[list[Team], list[Fixture]]:
    """Parse the raw schedule dict into (teams, fixtures).

    Teams are derived from all unique group-stage team1/team2 names.
    Fixture IDs: use openfootball `num` when present; otherwise mint by
    sorting all 104 matches by (date, time, team1, team2) and assigning 1..N.
    """
    matches = raw.get("matches", [])

    # ---- Teams: collect from group matches only ----
    group_names: set[str] = set()
    group_assignments: dict[str, str] = {}
    for m in matches:
        if "group" not in m:
            continue
        grp = m["group"].replace("Group ", "").strip()  # "Group A" -> "A"
        for key in ("team1", "team2"):
            name = m[key]
            if not is_placeholder(name):
                group_names.add(normalize(name))
                group_assignments[normalize(name)] = grp

    teams: list[Team] = []
    for name in CANONICAL_TEAMS:
        if name in group_names:
            teams.append(
                Team(
                    id=team_id_for(name),
                    name=name,
                    group=group_assignments.get(name),
                )
            )

    # ---- Fixtures ----
    # Two passes: first collect all, then assign ids to num-less entries.
    raw_fixtures: list[dict] = []
    for m in matches:
        raw_fixtures.append(m)

    # Sort all matches for deterministic id minting.
    def sort_key(m: dict) -> tuple:
        """Return a stable chronological key for fixtures without source ids."""
        return (
            m.get("date", ""),
            m.get("time", ""),
            m.get("team1", ""),
            m.get("team2", ""),
        )

    sorted_matches = sorted(raw_fixtures, key=sort_key)
    # Pre-assign surrogate ids to matches without `num`.
    next_surrogate = 1
    surrogate_map: dict[int, int] = {}  # index-in-sorted → assigned id
    used_nums = {m["num"] for m in sorted_matches if "num" in m}
    # Surrogates start after the highest explicit num (or 200 if none).
    surrogate_base = max(used_nums, default=200)
    for idx, m in enumerate(sorted_matches):
        if "num" not in m:
            while (surrogate_base + next_surrogate) in used_nums:
                next_surrogate += 1
            surrogate_map[idx] = surrogate_base + next_surrogate
            next_surrogate += 1

    fixtures: list[Fixture] = []
    for idx, m in enumerate(sorted_matches):
        fixture_id = m["num"] if "num" in m else surrogate_map[idx]
        kickoff = _parse_kickoff(m["date"], m["time"])

        has_group = "group" in m
        if has_group:
            stage = Stage.GROUP
            grp = m["group"].replace("Group ", "").strip()
            t1 = normalize(m["team1"])
            t2 = normalize(m["team2"])
            fixtures.append(
                Fixture(
                    id=fixture_id,
                    stage=stage,
                    group=grp,
                    kickoff=kickoff,
                    venue=m.get("ground"),
                    home_id=team_id_for(t1),
                    away_id=team_id_for(t2),
                )
            )
        else:
            round_name = m["round"]
            stage = _ROUND_TO_STAGE.get(round_name)
            if stage is None:
                raise ValueError(f"Unknown round name: {round_name!r}")
            t1 = m["team1"]
            t2 = m["team2"]
            fixtures.append(
                Fixture(
                    id=fixture_id,
                    stage=stage,
                    kickoff=kickoff,
                    venue=m.get("ground"),
                    home_label=t1,
                    away_label=t2,
                )
            )

    return teams, fixtures


def _parse_kickoff(date_str: str, time_str: str) -> datetime:
    """Convert openfootball date + time-with-offset to UTC datetime.

    time_str examples: "13:00 UTC-6", "12:00 UTC-7", "18:00 UTC+3"
    The offset is what you ADD to local time to get UTC, so UTC-6 means local+6=UTC.
    """
    m = re.search(r"UTC([+-]\d+)", time_str)
    if not m:
        raise ValueError(f"Cannot parse UTC offset from time string: {time_str!r}")
    offset_hours = int(m.group(1))
    hhmm = time_str.split()[0]  # "13:00"
    hour, minute = map(int, hhmm.split(":"))

    # Build a naive local datetime, then subtract the offset to get UTC.
    year, mon, day = map(int, date_str.split("-"))
    local_naive = datetime(year, mon, day, hour, minute)
    utc_dt = local_naive - timedelta(hours=offset_hours)
    return utc_dt.replace(tzinfo=timezone.utc)
