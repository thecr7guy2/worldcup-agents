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
    ModelSpec("GPT-5.5", "openai/gpt-5.5"),
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


# ---- Competition constants (all tunable in one place) ----
STARTING_BANKROLL = 1_000_000.0  # each competitor starts here
MAX_STAKE_FRACTION = 0.25  # max fraction of current bankroll riskable per match
IDLE_DECAY = 0.005  # fraction lost on un-staked bankroll per matchday (anti-cowardice)
BANKRUPT_FLOOR = 10_000.0  # at/below this, the agent is bust
REBUY_AMOUNT = 100_000.0  # a smaller "second life" granted on bust
MAX_LIVES = 1  # number of re-buys allowed

# Accuracy leaderboard scoring (DESIGN §6) — graded off the PREDICT step, stakes
# ignored. A correct exact 90' scoreline doubles the reward of a correct outcome.
POINTS_CORRECT_OUTCOME = 1  # right 1X2 result (winner / draw) but wrong score
POINTS_CORRECT_SCORE = 2  # right exact 90-minute scoreline (supersedes the above)
POINTS_CORRECT_ADVANCE = 1  # knockout only: correctly called who progressed (ET/pens);
# stacks on top of the 90' points, independent of them

# ---- Orchestrator scheduling windows (hours relative to kickoff) ----
# Build a fixture's briefing within this many hours before kickoff:
BRIEF_LEAD_HOURS = 24.0
# Run predict+bet within this many hours before kickoff:
BET_LEAD_HOURS = 3.0
# Wait this long after kickoff before trying to ingest a result:
RESULT_DELAY_HOURS = 2.5


settings = Settings()


def openrouter_ready() -> bool:
    """True if the OpenRouter key is set (all models need only this one)."""
    return bool(settings.openrouter_api_key)
