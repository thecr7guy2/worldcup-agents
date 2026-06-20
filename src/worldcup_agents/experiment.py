"""Version labels attached to every new prediction and bet."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

# Phase 1 (fixtures 103-106) used the blind forecast for the EV guard.
# Phase 2 introduced post-market p_revised with a blind-forecast fallback (deployed live).
# Phase 3 (dev only, never live) failed closed when a non-pass omitted a valid p_revised.
# Phase 4 (dev only, never live) required a complete post-market 1X2 distribution.
# Phase 5 used a complete revised distribution, EV gate, half-Kelly ceiling, minimum floor,
# and stage-ramped caps. Live results still produced zero favorite bets because flat blind
# probabilities and payout-seeking narratives made longshots look attractive.
# Phase 6 removes the probability machinery from Step 2. The immutable blind forecast defines
# eligibility: a pick must sit within 10 points of the top read. Odds choose among eligible
# outcomes; the model requests a fixed conviction tier; the engine only enforces eligibility,
# the stage tier ceiling, and aggregate exposure. A later prompt/rules revision briefly added
# a 2% tier, but live rows showed it became a meaningless default; v12 removed token bets and
# restored 5% as the minimum non-pass tier. v13 turns each UTC matchday into a portfolio:
# agents see a stage-ramped target allocation as they lock individual fixtures, and unallocated
# target budget is penalized at matchday close.
EXPERIMENT_PHASE = "phase_6_coherent_tier_betting"

FORECAST_PROMPT_VERSION = "forecast_v3_calibrated_spread"
BET_PROMPT_VERSION = "bet_v14_conviction_sizing_no_floor_default"
# Rules unchanged from v11 — v14 is a prompt-framing change only (removed the
# minimum-tier-as-default anchor); segment analysis by BET_PROMPT_VERSION, not rules.
BETTING_RULES_VERSION = "rules_v11_gap10_portfolio_targets_tiers5_10_15_20_25_30_exposure50"

HUMAN_FORECAST_VERSION = "human_forecast_v1"
HUMAN_BET_VERSION = "human_bet_v1"
HUMAN_RULES_VERSION = "human_rules_v1_manual_25pct_cap"


@lru_cache(maxsize=1)
def git_commit() -> str:
    """Return the deployed Git SHA, marking an uncommitted checkout as dirty."""
    override = os.environ.get("WORLDCUP_GIT_COMMIT", "").strip()
    if override:
        return override

    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha
