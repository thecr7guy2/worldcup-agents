"""Canonical team names and ID minting for World Cup 2026.

Both openfootball and The Odds API use byte-identical names for all 48 teams
(verified 2026-06-05). The alias map below handles known variant spellings that
may appear in The Odds API mid-tournament.
"""

from __future__ import annotations

# Frozen — qualification is complete. Both sources agree on these exact strings.
CANONICAL_TEAMS: list[str] = sorted(
    [
        "Algeria",
        "Argentina",
        "Australia",
        "Austria",
        "Belgium",
        "Bosnia & Herzegovina",
        "Brazil",
        "Canada",
        "Cape Verde",
        "Colombia",
        "Croatia",
        "Curaçao",
        "Czech Republic",
        "DR Congo",
        "Ecuador",
        "Egypt",
        "England",
        "France",
        "Germany",
        "Ghana",
        "Haiti",
        "Iran",
        "Iraq",
        "Ivory Coast",
        "Japan",
        "Jordan",
        "Mexico",
        "Morocco",
        "Netherlands",
        "New Zealand",
        "Norway",
        "Panama",
        "Paraguay",
        "Portugal",
        "Qatar",
        "Saudi Arabia",
        "Scotland",
        "Senegal",
        "South Africa",
        "South Korea",
        "Spain",
        "Sweden",
        "Switzerland",
        "Tunisia",
        "Turkey",
        "USA",
        "Uruguay",
        "Uzbekistan",
    ]
)

# Aliases: known Odds-API variant → canonical name.
_ALIASES: dict[str, str] = {
    "Türkiye": "Turkey",
    "United States": "USA",
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
    "Côte d'Ivoire": "Ivory Coast",
    "Cabo Verde": "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Czechia": "Czech Republic",
    "Democratic Republic of Congo": "DR Congo",
    "Republic of Ireland": "Ireland",  # not in WC2026 but guard anyway
}

_NAME_SET: frozenset[str] = frozenset(CANONICAL_TEAMS)
_INDEX: dict[str, int] = {name: i + 1 for i, name in enumerate(CANONICAL_TEAMS)}


def normalize(name: str) -> str:
    """Return the canonical name for a raw team name string.

    Strips whitespace, applies the alias map. Raises ValueError if the result
    is not in CANONICAL_TEAMS — callers must handle or propagate this loudly.
    """
    stripped = name.strip()
    canonical = _ALIASES.get(stripped, stripped)
    if canonical not in _NAME_SET:
        raise ValueError(f"Unknown team name: {name!r} (normalized: {canonical!r})")
    return canonical


def team_id_for(name: str) -> int:
    """Return the 1-based surrogate id for a canonical team name."""
    canonical = normalize(name)
    return _INDEX[canonical]


def is_placeholder(name: str) -> bool:
    """True if name is a bracket label (e.g. '2A', 'W73'), not a real team."""
    stripped = name.strip()
    return stripped not in _NAME_SET and stripped not in _ALIASES
