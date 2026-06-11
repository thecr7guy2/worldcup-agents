"""Minimal OpenRouter client.

All model traffic goes through OpenRouter's OpenAI-compatible chat endpoint.
`complete()` returns the response text plus a ModelCall (token counts + the
actual billed cost OpenRouter reports) ready to log for the technical report.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

import httpx

from .config import OPENROUTER_BASE_URL, settings
from .models import ModelCall

# Free OpenRouter models are transiently rate-limited (HTTP 429) and providers
# occasionally 5xx. Retry a few times with linear backoff before giving up.
_RETRY_STATUS = {429, 500, 502, 503, 504}

CHAT_URL = f"{OPENROUTER_BASE_URL}/chat/completions"


class LLMError(RuntimeError):
    """Raised when an OpenRouter call fails or returns no usable content."""


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates ``` fences / prose).

    Shared by every structured-output caller (predict, bet, result ingestion) so the
    tolerance rules live in one place — the LLM-output boundary.
    """
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    start = cleaned.find("{")
    if start == -1:
        raise LLMError(f"no JSON object in reply: {text[:200]!r}")
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError as e:
                    raise LLMError(
                        f"bad JSON in reply: {e}; {cleaned[start:i+1][:200]!r}"
                    )
    raise LLMError(f"unterminated JSON object in reply: {text[:200]!r}")


def complete(
    model_id: str,
    prompt: str,
    *,
    model_name: str,
    step: str,
    fixture_id: int | None = None,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    # Reasoning models at effort=high routinely think for minutes before answering;
    # 120s timed out exactly the calls we care most about (predict/bet near kickoff),
    # and each timeout burns a retry slot inside the tight pre-kickoff window.
    timeout: float = 300.0,
    max_retries: int = 3,
    backoff: float = 3.0,
    web_search: bool = False,
    web_max_results: int = 5,
    reasoning_effort: str | None = None,
) -> tuple[str, ModelCall]:
    """Call a model via OpenRouter and return (text, telemetry).

    Retries transient rate-limits/5xx with linear backoff. Raises LLMError on
    persistent transport errors, non-200 responses, or empty output.

    When `web_search` is set, OpenRouter's `web` plugin runs a live search
    server-side and injects the (dated) results before the model reads the
    prompt — this is how the intelligence agent gets facts. The search cost is
    billed into `usage.cost`, so it flows through to `ModelCall.cost_usd`.
    Web search needs a funded OpenRouter balance (it is not a free-tier feature).

    `reasoning_effort` ("low"/"medium"/"high") bounds how much a reasoning model
    spends on hidden thinking. Heavy reasoners (e.g. Kimi) can otherwise consume
    the entire `max_tokens` budget on reasoning and return empty content; "low"
    keeps room for the actual answer on constrained tasks. Ignored by non-reasoning
    models.
    """
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not set")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "usage": {"include": True},  # ask OpenRouter to include billed cost
    }
    if web_search:
        body["plugins"] = [{"id": "web", "max_results": web_max_results}]
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}

    last_err = ""
    for attempt in range(max_retries + 1):
        start = time.monotonic()
        try:
            resp = httpx.post(CHAT_URL, json=body, headers=headers, timeout=timeout)
        except httpx.HTTPError as e:
            last_err = f"transport error: {e}"
            if attempt < max_retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise LLMError(f"{model_id}: {last_err}") from e
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code in _RETRY_STATUS and attempt < max_retries:
            time.sleep(backoff * (attempt + 1))
            continue
        if resp.status_code != 200:
            raise LLMError(f"{model_id}: HTTP {resp.status_code}: {resp.text[:300]}")

        # A 200 whose body is not parseable JSON is a transient provider/transport artifact
        # (observed: a malformed/partial body on deepseek-v4-pro that surfaced as a raw
        # JSONDecodeError and crashed the predict step with no retry). Treat it like a 5xx.
        try:
            data = resp.json()
        except ValueError as e:
            last_err = f"unparseable 200 body: {e}"
            if attempt < max_retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise LLMError(f"{model_id}: {last_err}") from e
        choices = data.get("choices")
        finish = choices[0].get("finish_reason") if choices else None
        message = (choices[0].get("message") or {}) if choices else {}
        text = message.get("content") or ""

        # OpenRouter returns HTTP 200 with finish_reason="error" (or no choices at all)
        # when the UPSTREAM provider errors mid-generation — observed as a transient Baidu
        # hiccup on deepseek-v4-pro that the model otherwise handles fine. The status-code
        # retry above never sees these (they are 200s), so a briefing died on a blip with no
        # retry. Treat a provider error / missing choices / an empty answer that did NOT
        # merely hit the token cap as transient and retry; a real finish_reason="length"
        # still falls through to the max_tokens hint below.
        provider_failed = (
            not choices
            or finish == "error"
            or (not text.strip() and finish != "length")
        )
        if provider_failed and attempt < max_retries:
            err = (choices[0].get("error") if choices else None) or data.get("error")
            last_err = f"finish_reason={finish}; {str(err)[:200]}"
            time.sleep(backoff * (attempt + 1))
            continue
        if not choices:
            raise LLMError(f"{model_id}: no choices in response: {str(data)[:300]}")
        break
    # OpenRouter surfaces a model's exposed reasoning trace (when the provider returns
    # one) as `message.reasoning`. Captured verbatim: the technical report's "why did
    # this agent behave that way" analysis needs the full trace, not just the 2-4
    # sentence summary the agent puts in its JSON answer.
    reasoning = message.get("reasoning")
    if reasoning is not None and not isinstance(reasoning, str):
        reasoning = str(reasoning)
    # Web-search calls return citation annotations (the URLs the search injected) —
    # the audit trail of which sources informed a dossier/briefing/result.
    annotations = message.get("annotations")
    try:
        annotations_json = json.dumps(annotations) if annotations else None
    except (TypeError, ValueError):
        annotations_json = None

    usage = data.get("usage") or {}
    call = ModelCall(
        model_name=model_name,
        step=step,
        fixture_id=fixture_id,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        cost_usd=float(usage.get("cost") or 0.0),
        latency_ms=latency_ms,
        generation_id=data.get("id"),
        response_text=text or None,
        reasoning_text=reasoning or None,
        prompt_text=prompt,
        annotations_json=annotations_json,
        created_at=datetime.now(timezone.utc),
    )
    if not text.strip():
        raise LLMError(
            f"{model_id}: empty content (finish_reason={finish}; "
            f"raise max_tokens for reasoning models). usage={usage}"
        )
    return text, call
