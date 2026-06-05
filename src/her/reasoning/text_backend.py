"""Cloud-or-local router for the app's plain chat-completion helpers.

The memory summarizer, the character profiler and the skill compiler all make a
single non-streaming Chat-Completions call and read back the assistant text
(JSON for the first two, an AppleScript for the compiler). This module is the
one place that decides *where* that call goes:

* ``llm_backend == "cloud"`` (default) → OpenAI (``api.openai.com``), billed
  against ``OPENAI_API_KEY``;
* ``llm_backend == "local"`` → an Ollama server speaking the OpenAI-compatible
  API (``LOCAL_LLM_BASE_URL``), free and on-device.

Both endpoints accept the same request shape, so the helpers just hand us their
messages plus the *cloud* model name; in local mode we swap in the configured
local model. Every call is best-effort: any failure returns ``None``/empty so a
missing key, an unreachable Ollama or malformed output simply means that one
feature contributes nothing this session.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def is_local() -> bool:
    return settings.llm_backend.strip().lower() == "local"


def _endpoint(local_model: str | None, cloud_model: str) -> tuple[str, str, dict] | None:
    """Return ``(url, model, headers)`` for the active backend, or ``None`` when
    the cloud backend is selected but no API key is configured."""
    if is_local():
        base = settings.local_llm_base_url.rstrip("/")
        model = local_model or settings.local_llm_model
        return f"{base}/chat/completions", model, {"Content-Type": "application/json"}
    if not settings.openai_api_key:
        return None
    return (
        _OPENAI_URL,
        cloud_model,
        {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
    )


async def _post(payload: dict, headers: dict, url: str, timeout: float) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        log.exception("text_backend: chat call to %s failed", url)
        return None


async def chat_text(
    messages: list[dict],
    *,
    cloud_model: str,
    local_model: str | None = None,
    temperature: float | None = None,
    timeout: float = 120.0,
) -> str | None:
    """Run one chat completion and return the raw assistant text (or None)."""
    target = _endpoint(local_model, cloud_model)
    if target is None:
        log.warning("text_backend: no OPENAI_API_KEY (cloud backend), skipping call")
        return None
    url, model, headers = target
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    return await _post(payload, headers, url, timeout)


async def chat_json(
    messages: list[dict],
    *,
    cloud_model: str,
    local_model: str | None = None,
    temperature: float = 0.3,
    timeout: float = 30.0,
) -> dict | None:
    """Run one chat completion constrained to a JSON object and return it parsed.

    The prompts themselves already instruct the model to reply with JSON only;
    ``response_format`` enforces it on both OpenAI and recent Ollama builds.
    """
    target = _endpoint(local_model, cloud_model)
    if target is None:
        log.warning("text_backend: no OPENAI_API_KEY (cloud backend), skipping call")
        return None
    url, model, headers = target
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    raw = await _post(payload, headers, url, timeout)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("text_backend: response was not valid JSON")
        return None
