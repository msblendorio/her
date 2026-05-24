"""Tracks token usage and estimated cost for the running session.

Numbers come from `response.done.response.usage` events emitted by the Realtime
API. The price table below is an approximation as of early 2026 — update
`PRICES` if OpenAI changes its rates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


# USD per 1,000,000 tokens, per-model. Cached entries cover the discounted rate
# applied to repeated prompt context. Values are approximate and may drift.
PRICES: dict[str, dict[str, float]] = {
    "gpt-realtime-mini": {
        "text_in": 0.60, "text_in_cached": 0.30,
        "text_out": 2.40,
        "audio_in": 10.00, "audio_in_cached": 0.30,
        "audio_out": 20.00,
    },
    "gpt-realtime": {
        "text_in": 4.00, "text_in_cached": 0.40,
        "text_out": 16.00,
        "audio_in": 32.00, "audio_in_cached": 0.40,
        "audio_out": 64.00,
    },
}
DEFAULT_PRICES = PRICES["gpt-realtime-mini"]


def _prices_for(model: str) -> dict[str, float]:
    # Match the longest prefix (e.g. "gpt-realtime-mini-2025-10-06" -> mini).
    if "mini" in model:
        return PRICES["gpt-realtime-mini"]
    if model.startswith("gpt-realtime"):
        return PRICES["gpt-realtime"]
    return DEFAULT_PRICES


@dataclass
class UsageTracker:
    model: str = "gpt-realtime-mini"
    text_in: int = 0
    text_in_cached: int = 0
    text_out: int = 0
    audio_in: int = 0
    audio_in_cached: int = 0
    audio_out: int = 0
    responses: int = 0
    cost_usd: float = 0.0

    def reset(self, model: str = "") -> None:
        self.model = model or self.model
        self.text_in = self.text_in_cached = self.text_out = 0
        self.audio_in = self.audio_in_cached = self.audio_out = 0
        self.responses = 0
        self.cost_usd = 0.0

    def record(self, usage: dict | None) -> None:
        """Apply one `response.done.response.usage` block."""
        if not usage:
            return
        in_details = usage.get("input_token_details", {}) or {}
        out_details = usage.get("output_token_details", {}) or {}
        cached_details = (in_details.get("cached_tokens_details") or {})

        cached_total = int(in_details.get("cached_tokens", 0) or 0)
        cached_text = int(cached_details.get("text_tokens", 0) or 0)
        cached_audio = int(cached_details.get("audio_tokens", 0) or 0)
        # If the API only reported a flat cached_tokens count, assume audio
        # (the dominant input modality for this app).
        if cached_total and not (cached_text or cached_audio):
            cached_audio = cached_total

        total_text_in = int(in_details.get("text_tokens", 0) or 0)
        total_audio_in = int(in_details.get("audio_tokens", 0) or 0)

        # Cached tokens are billed at the cheaper cached rate; subtract them
        # from the regular bucket to avoid double-charging.
        text_in_billed = max(total_text_in - cached_text, 0)
        audio_in_billed = max(total_audio_in - cached_audio, 0)

        text_out = int(out_details.get("text_tokens", 0) or 0)
        audio_out = int(out_details.get("audio_tokens", 0) or 0)

        self.text_in += text_in_billed
        self.text_in_cached += cached_text
        self.audio_in += audio_in_billed
        self.audio_in_cached += cached_audio
        self.text_out += text_out
        self.audio_out += audio_out
        self.responses += 1

        p = _prices_for(self.model)
        added = (
            text_in_billed   * p["text_in"]
          + cached_text      * p["text_in_cached"]
          + audio_in_billed  * p["audio_in"]
          + cached_audio     * p["audio_in_cached"]
          + text_out         * p["text_out"]
          + audio_out        * p["audio_out"]
        ) / 1_000_000.0
        self.cost_usd += added

    def snapshot(self) -> dict:
        return {
            "model": self.model,
            "responses": self.responses,
            "tokens": {
                "text_in": self.text_in,
                "text_in_cached": self.text_in_cached,
                "audio_in": self.audio_in,
                "audio_in_cached": self.audio_in_cached,
                "text_out": self.text_out,
                "audio_out": self.audio_out,
                "total": (
                    self.text_in + self.text_in_cached
                    + self.audio_in + self.audio_in_cached
                    + self.text_out + self.audio_out
                ),
            },
            "cost_usd": round(self.cost_usd, 5),
        }


usage = UsageTracker()
