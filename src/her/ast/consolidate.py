"""Phase 1 — the "sleep" / consolidation pass (slow loop).

Runs after N sessions (or nightly when idle, in a later phase). In Phase 1 it:

1. prunes raw turns past the retention window (privacy),
2. rebuilds the **Style Card** from the captured turns,
3. (best-effort) enriches the card's one-line "voice" with a cheap chat model,
4. rebuilds the few-shot **retrieval** index.

The heavier "reflection" (self-critiques, skill/routine mining, dataset building
for distillation) belongs to Phase 2+ and is left as a documented stub below.
Everything here is CPU-only and safe to run fire-and-forget at session end.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from ..core.event_bus import bus
from ..reasoning.text_backend import chat_json
from .retrieval import Retrieval
from .store import AstStore
from .style import StyleCard, build_style_card

log = logging.getLogger(__name__)

_VOICE_PROMPT = (
    "You distill a ONE-LINE description of a user's conversational voice, to help "
    "an assistant mirror it. Given a sample of their messages, reply with JSON: "
    '{\"voice\": \"<one short line, max 160 chars, in the user\'s own language>\"}. '
    "Describe tone/quirks/directness — not topics. Reply ONLY with the JSON."
)


async def _enrich_voice(card: StyleCard, sample_user_texts: list[str]) -> str:
    """Best-effort: ask the cheap chat model for a one-line voice description.
    Returns the prior voice (or empty) on any failure — never raises."""
    if len(sample_user_texts) < 4:
        return card.voice
    sample = "\n".join(f"- {t}" for t in sample_user_texts[-20:])
    try:
        parsed = await chat_json(
            [
                {"role": "system", "content": _VOICE_PROMPT},
                {"role": "user", "content": f"User messages:\n{sample}"},
            ],
            cloud_model=settings.memory_summarizer_model,
            temperature=0.3,
        )
    except Exception:
        log.exception("ast: voice enrichment call failed")
        return card.voice
    if isinstance(parsed, dict) and isinstance(parsed.get("voice"), str):
        return parsed["voice"].strip()[:160]
    return card.voice


async def consolidate(store: AstStore) -> dict:
    """Run a Phase 1 consolidation pass. Returns a summary dict for logging/UI."""
    bus.publish("ast.status", {"status": "consolidating"})
    log.info("ast: consolidation started")
    try:
        pruned = store.prune_retention(settings.ast_retention_days)

        turns = await asyncio.to_thread(store.recent_turns, 50)
        if not turns:
            log.info("ast: nothing to consolidate (no captured turns)")
            return {"pruned": pruned, "turns": 0, "style_updated": False, "indexed": 0}

        prev = store.load_style_card()
        previous = StyleCard.from_dict(prev) if prev else None
        card = await asyncio.to_thread(build_style_card, turns, previous)

        # Optional LLM enrichment of the one-line voice (best-effort).
        user_texts = [t["text"] for t in turns if t.get("role") == "user" and t.get("text")]
        card.voice = await _enrich_voice(card, user_texts)

        store.save_style_card(card.to_dict())

        # Rebuild the retrieval index (no-op without the embedder dependency).
        indexed = await asyncio.to_thread(Retrieval(store).reindex, turns)

        log.info(
            "ast: consolidation done (turns=%d, length=%s, register=%s, indexed=%d)",
            card.turns_observed, card.length_pref, card.register, indexed,
        )
        return {
            "pruned": pruned,
            "turns": card.turns_observed,
            "style_updated": True,
            "length_pref": card.length_pref,
            "register": card.register,
            "indexed": indexed,
        }
    finally:
        bus.publish("ast.status", {"status": "idle"})


async def reflect(store: AstStore) -> None:
    """Phase 2+ — deeper reflection: self-critiques over the period, personal
    knowledge-graph updates, skill/routine mining, and distillation dataset
    building. Not implemented yet (needs the dataset builder + trainer)."""
    raise NotImplementedError(
        "AST reflection (skill/routine mining + distillation dataset) is a "
        "Phase 2 feature — see future-features/AST_MODE_PLAN.md §6.2."
    )
