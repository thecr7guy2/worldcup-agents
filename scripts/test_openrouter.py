"""Smoke-test the active OpenRouter lineup: call each model once, report usage.

    uv run python scripts/test_openrouter.py

Useful for checking which models are reachable (free tiers appear/disappear) and
that telemetry (tokens + cost) comes back correctly.
"""

from worldcup_agents.config import INTELLIGENCE_MODEL, PREDICTION_MODELS, settings
from worldcup_agents.llm import LLMError, complete


def main() -> None:
    """Send minimal completions to verify every configured OpenRouter model."""
    if not settings.openrouter_api_key:
        print("OPENROUTER_API_KEY not set — fill it into .env")
        return

    lineup = [INTELLIGENCE_MODEL, *PREDICTION_MODELS]
    print(f"Testing {len(lineup)} models\n")

    ok = 0
    for spec in lineup:
        try:
            text, call = complete(
                spec.model_id,
                "In one short sentence: who wins the 2026 World Cup, and why?",
                model_name=spec.name,
                step="smoke",
                max_tokens=400,  # headroom for reasoning models (they spend tokens thinking)
            )
            snippet = " ".join(text.split())[:100]
            print(f"OK   {spec.name:<16} {spec.model_id}")
            print(
                f"     tokens={call.total_tokens} "
                f"cost=${call.cost_usd:.6f} {call.latency_ms}ms"
            )
            print(f"     -> {snippet}")
            ok += 1
        except LLMError as e:
            print(f"FAIL {spec.name:<16} {spec.model_id}")
            print(f"     {e}")
        print()

    print(f"{ok}/{len(lineup)} models reachable")


if __name__ == "__main__":
    main()
