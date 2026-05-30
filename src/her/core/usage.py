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


# Anthropic (Claude) pricing for the Cowork / knowledge-wiki calls, USD per
# 1,000,000 tokens. Cache reads bill at ~0.1x input; 5-minute ephemeral cache
# writes at ~1.25x input (the TTL CoworkClient uses). Approximate, may drift.
ANTHROPIC_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"in": 5.00, "out": 25.00},
    "claude-opus-4-7": {"in": 5.00, "out": 25.00},
    "claude-opus-4-6": {"in": 5.00, "out": 25.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
}
ANTHROPIC_DEFAULT_PRICES = ANTHROPIC_PRICES["claude-opus-4-8"]


def _prices_for(model: str) -> dict[str, float]:
    # Match the longest prefix (e.g. "gpt-realtime-mini-2025-10-06" -> mini).
    if "mini" in model:
        return PRICES["gpt-realtime-mini"]
    if model.startswith("gpt-realtime"):
        return PRICES["gpt-realtime"]
    return DEFAULT_PRICES


def _anthropic_prices_for(model: str) -> dict[str, float]:
    for key, prices in ANTHROPIC_PRICES.items():
        if model.startswith(key):
            return prices
    if "haiku" in model:
        return ANTHROPIC_PRICES["claude-haiku-4-5"]
    if "sonnet" in model:
        return ANTHROPIC_PRICES["claude-sonnet-4-6"]
    return ANTHROPIC_DEFAULT_PRICES


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

    # Anthropic (Cowork / knowledge wiki) accounting, tracked separately from
    # the OpenAI realtime buckets so the token breakdown above stays clean.
    anthropic_model: str = ""
    anthropic_in: int = 0
    anthropic_out: int = 0
    anthropic_cache_read: int = 0
    anthropic_cache_write: int = 0
    anthropic_requests: int = 0
    anthropic_cost_usd: float = 0.0

    def reset(self, model: str = "") -> None:
        self.model = model or self.model
        self.text_in = self.text_in_cached = self.text_out = 0
        self.audio_in = self.audio_in_cached = self.audio_out = 0
        self.responses = 0
        self.cost_usd = 0.0
        self.anthropic_in = self.anthropic_out = 0
        self.anthropic_cache_read = self.anthropic_cache_write = 0
        self.anthropic_requests = 0
        self.anthropic_cost_usd = 0.0

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

    def record_anthropic(self, usage: object | None, model: str = "") -> None:
        """Apply one Anthropic Messages ``usage`` block (object or dict).

        Reads ``input_tokens`` / ``output_tokens`` / ``cache_read_input_tokens``
        / ``cache_creation_input_tokens`` defensively (the SDK returns a pydantic
        object; a plain dict also works) and adds the cost to the Anthropic
        bucket, which the snapshot folds into the running total.
        """
        if usage is None:
            return

        def _g(name: str) -> int:
            if isinstance(usage, dict):
                return int(usage.get(name) or 0)
            return int(getattr(usage, name, 0) or 0)

        if model:
            self.anthropic_model = model

        inp = _g("input_tokens")
        out = _g("output_tokens")
        cache_read = _g("cache_read_input_tokens")
        cache_write = _g("cache_creation_input_tokens")

        p = _anthropic_prices_for(self.anthropic_model or model)
        added = (
            inp         * p["in"]
          + out         * p["out"]
          + cache_read  * (p["in"] * 0.1)
          + cache_write * (p["in"] * 1.25)
        ) / 1_000_000.0

        self.anthropic_in += inp
        self.anthropic_out += out
        self.anthropic_cache_read += cache_read
        self.anthropic_cache_write += cache_write
        self.anthropic_requests += 1
        self.anthropic_cost_usd += added

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
            # Anthropic (Cowork / wiki) cost, plus the combined total the
            # status bar displays. cost_usd above stays OpenAI-only.
            "anthropic": {
                "model": self.anthropic_model,
                "requests": self.anthropic_requests,
                "input_tokens": self.anthropic_in,
                "output_tokens": self.anthropic_out,
                "cache_read": self.anthropic_cache_read,
                "cache_write": self.anthropic_cache_write,
                "cost_usd": round(self.anthropic_cost_usd, 5),
            },
            "cost_total_usd": round(self.cost_usd + self.anthropic_cost_usd, 5),
        }


usage = UsageTracker()
