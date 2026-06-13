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
# Phase 5 keeps the complete distribution + model-owned pick, replaces the blind fallback with
#   a single retry, and adds engine-enforced stake protection: a HALF-Kelly ceiling (held flat
#   — uncalibrated probabilities make full Kelly unsafe), a per-match cap that ramps 25% -> 50%
#   by the final, an aggregate-exposure cap (50%), a 2% minimum-bet floor, and a 1.5% EV gate so
#   the floor only ever lifts real edges, not rounding noise. The bet prompt reframes passing:
#   bet a genuine edge, pass only on a true toss-up.
EXPERIMENT_PHASE = "phase_5_hybrid_risk_engine"

FORECAST_PROMPT_VERSION = "forecast_v2_distribution"  # Step 1 unchanged
BET_PROMPT_VERSION = "bet_v7_bet_your_edge_ev_gated"
BETTING_RULES_VERSION = "rules_v7_halfkelly_capramp_minfloor2pct_exposure50_ev_015"

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
