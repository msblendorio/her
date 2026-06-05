"""Shared builder for Samantha's system instructions.

Both the hosted :class:`RealtimeSession` (OpenAI Realtime) and the on-device
:class:`LocalRealtimeSession` (faster-whisper → Ollama → Kokoro) need to feed
the model the exact same persona prompt — system prompt, time/space awareness,
recall block, accessibility / empathy addenda, the learned-skill index and the
Cowork nudge. Keeping it in one place guarantees the two backends behave
identically.
"""
from __future__ import annotations

from ..config import settings
from ..cowork.client import client as cowork_client
from ..i18n import (
    accessibility_addendum,
    cowork_addendum,
    empathy_addendum,
    learned_skills_addendum,
    system_prompt,
    time_space_awareness,
)
from ..memory.character import CharacterProfile


def build_instructions(
    *,
    language: str,
    extra_instructions: str = "",
    accessibility: bool = False,
    character: CharacterProfile | None = None,
    empathy_mood: str = "calm",
    learned_skills: list[dict] | None = None,
) -> str:
    """Assemble the full system prompt from its parts.

    ``time_space_awareness`` is re-evaluated on every call so the date and
    local time stay fresh whenever instructions are rebuilt (e.g. when an
    accessibility / empathy toggle re-pushes them mid-session).
    """
    parts = [system_prompt(language)]
    parts.append(time_space_awareness(language))
    if extra_instructions:
        parts.append(extra_instructions)
    if accessibility:
        parts.append(accessibility_addendum(language))
    # Empathy addendum is always appended: even without a profile (first
    # session) the mood directive alone is useful; on later sessions the
    # persisted profile block kicks in too.
    parts.append(empathy_addendum(character, empathy_mood or "calm", language))
    skills_block = learned_skills_addendum(list(learned_skills or []), language)
    if skills_block:
        parts.append(skills_block)
    # Cowork nudge only when it's enabled and actually reachable (an Anthropic
    # credential, or the local LLM backend).
    if settings.cowork_enabled and cowork_client.is_configured():
        parts.append(cowork_addendum(language))
    return "\n\n".join(parts)
