"""Central configuration: secrets loading and the model registry.

All model traffic goes through OpenRouter — one key, one OpenAI-compatible
endpoint — so the registry just maps a display name to an OpenRouter model id.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets and runtime config, read from the environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Data sources
    api_football_key: str = ""
    odds_api_key: str = ""

    # Every LLM is reached through OpenRouter — a single key.
    openrouter_api_key: str = ""

    # The secret "Human Challenger" feature (an 8th, human competitor betting under the
    # same rules). `challenger_key` is the passphrase that unlocks the hidden betting
    # console — empty disables the feature entirely (no key, no writes). `challenger_name`
    # is the human's display name / model_name in the competitor table.
    challenger_key: str = ""
    challenger_name: str = "You"

    # Shared API key for the read-only "friend" bet endpoint (/api/external/bet). Empty
    # disables the route entirely (404). Anyone with this key can read any models locked
    # pick/stake/reasoning — it grants no writes and never exposes the Human Challenger.
    friend_api_key: str = ""

    # Public-site visitor geography. `track_ingest_key` is a shared secret the Next edge sends
    # with each /api/track call so the public can't forge visits; empty disables ingest (the
    # endpoint rejects everything). `geo_lookup_url` is a `{ip}`-templated free geo-IP endpoint;
    # only derived country/region is ever stored.
    track_ingest_key: str = ""
    geo_lookup_url: str = "https://ipwho.is/{ip}"


# OpenRouter's OpenAI-compatible base URL.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class ModelSpec:
    """One competitor (or the intelligence agent) in the lineup."""

    name: str  # display name on the leaderboard
    model_id: str  # OpenRouter model id


# The competing models — all reached through OpenRouter, all frontier-tier (per
# the user: prediction cost is low enough to run top models). Slugs drift as
# providers ship new versions; verify at https://openrouter.ai/models if a call
# starts failing with an unknown-model error.
PREDICTION_MODELS: list[ModelSpec] = [
    ModelSpec("GPT 5.5", "openai/gpt-5.5"),
    ModelSpec("Opus-4.8", "anthropic/claude-opus-4.8"),
    ModelSpec("MiniMax-M3", "minimax/minimax-m3"),
    ModelSpec("Kimi-K2.6", "moonshotai/kimi-k2.6"),
    ModelSpec("DeepSeek-V4-Pro", "deepseek/deepseek-v4-pro"),
    ModelSpec("Gemini-3.1-Pro", "google/gemini-3.1-pro-preview"),
    ModelSpec("Qwen3.7-Max", "qwen/qwen3.7-max"),
]

# The single intelligence agent that builds the shared dossiers and briefings.
# DeepSeek V4 Pro: frontier-class reasoning at ~1/12th of Opus's cost, 1M context
# (handles the large web-search content injected per call).
INTELLIGENCE_MODEL: ModelSpec = ModelSpec("Intelligence", "deepseek/deepseek-v4-pro")


# ---- Tournament structure ----
GROUP_LETTERS = "ABCDEFGHIJKL"  # the 12 groups A..L


# ---- Competition constants (all tunable in one place) ----
STARTING_BANKROLL = 1_000_000.0  # each competitor starts here
MAX_STAKE_FRACTION = 0.25  # max fraction of current bankroll riskable per match
IDLE_DECAY = 0.005  # fraction lost on un-staked bankroll per matchday (anti-cowardice)
BANKRUPT_FLOOR = 10_000.0  # at/below this, the agent is bust
REBUY_AMOUNT = 100_000.0  # a smaller "second life" granted on bust
MAX_LIVES = 1  # number of re-buys allowed

# The secret Human Challenger competes under all of the constants above. While False he is
# hidden from every public board (he still bets, settles, and decays exactly like the AIs —
# only his visibility is suppressed). Flip to True after the tournament to reveal his
# standing on the public site; no other code change is needed.
CHALLENGER_PUBLIC = False

# Accuracy leaderboard scoring (DESIGN §6) — graded off the PREDICT step, stakes
# ignored. A correct exact 90' scoreline doubles the reward of a correct outcome.
POINTS_CORRECT_OUTCOME = 1  # right 1X2 result (winner / draw) but wrong score
POINTS_CORRECT_SCORE = 2  # right exact 90-minute scoreline (supersedes the above)
POINTS_CORRECT_ADVANCE = 1  # knockout only: correctly called who progressed (ET/pens);
# stacks on top of the 90' points, independent of them

# ---- Intelligence research depth ----
# Results per OpenRouter web search for intelligence calls. One broad search has to cover
# availability, form, tactics, stakes, and conditions, so the default of 5 is too thin;
# 12 gives the agent enough sources to corroborate availability claims.
INTEL_WEB_MAX_RESULTS = 12

# Completion-token ceiling for intelligence calls. The intelligence model is a reasoning
# model: a tight cap (3-4k) gets entirely consumed by hidden reasoning, leaving empty
# content and a failed briefing. The ceiling is not a target — billed only on use — so we
# set it generously (matching the predictors) so reasoning never starves the answer.
INTEL_MAX_TOKENS = 20000


# ---- Orchestrator scheduling windows (hours relative to kickoff) ----
# Build a fixture's briefing within this many hours before kickoff:
BRIEF_LEAD_HOURS = 24.0
# Fetch the late update (confirmed XI / injuries / weather) in its OWN window, a step
# BEFORE predictions, so official lineups have time to land between the two. With a 15-min
# tick the update fires ~T-75..T-60 and predictions lock ~T-50..T-35 — at least one tick
# apart. The two windows must NOT overlap: LATE_UPDATE_LEAD_HOURS > BET_LEAD_HOURS.
LATE_UPDATE_LEAD_HOURS = 1.25  # ~75 min
# Run predict+bet within this many hours before kickoff (~50 min):
BET_LEAD_HOURS = 0.83
# Predict+bet are independent per model, so run them concurrently to fit the tight window
# even when several fixtures kick off together. Bounded to avoid hammering the gateway.
PREDICT_MAX_WORKERS = 6
# Refresh a cached late update at predict time if it is older than this many minutes, so
# confirmed lineups that landed since the first (~T-75) fetch are picked up before the lock.
LATE_UPDATE_REFRESH_MIN = 20.0
# Minimum expected value for a bet to stand: EV = model_prob(pick) * decimal_odds - 1. A bet
# that is non-positive by the model's OWN probabilities is internally inconsistent (negative
# expected value at the offered price) and is overridden to a pass. 0.0 = require any +EV.
MIN_BET_EV = 0.0
# Near-kickoff odds freshness: when a fixture is inside the late-update/bet horizon and its
# newest consensus snapshot is older than this, the tick triggers ONE targeted odds poll
# (1 API credit, covers all events). Keeps bets from being placed into a line up to 6 hours
# stale and gives the report a true closing-line reference. ~1-2 extra credits per kickoff
# slot — comfortably inside the 500/mo quota next to the 6-hourly baseline poll (~120/mo).
ODDS_REFRESH_MAX_AGE_MIN = 45.0
# Wait this long after kickoff before trying to ingest a result:
RESULT_DELAY_HOURS = 2.5
# A 90' score is written only after this many independent web-search reads agree (a wrong
# score corrupts settlement and both dossiers irreversibly). 1 = no confirmation; 2 = one
# confirming read. Extra reads cost ~one cheap intelligence call per finished match.
RESULT_CONFIRM_READS = 2


settings = Settings()


def openrouter_ready() -> bool:
    """True if the OpenRouter key is set (all models need only this one)."""
    return bool(settings.openrouter_api_key)
