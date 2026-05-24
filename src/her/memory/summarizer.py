"""Calls the OpenAI Chat Completions API to summarize a session.

Two flavors:

* `summarize(turns, ...)` — distills the spoken transcript (user ↔ Samantha)
  into a short textual recap + key facts.
* `summarize_visual(captions, ...)` — distills the timeline of webcam scene
  captions into a short visual recap + visual facts.

Both use a cheap text-only model (`gpt-4o-mini` by default) — not Realtime —
and ask for a structured JSON response. Output is consumed by the orchestrator,
which assembles a single `MemoryEntry` per session.
"""
from __future__ import annotations

import json
import logging

import httpx

from ..config import settings
from ..i18n import summarizer_prompt, visual_summarizer_prompt
from .store import MemoryEntry, now_iso

log = logging.getLogger(__name__)

CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Per-language transcript labels (the speaker tags shown to the summarizer).
_USER_LABEL = {"it": "Utente", "en": "User", "es": "Usuario", "fr": "Utilisateur", "de": "Nutzer"}


def _build_messages(turns: list[tuple[str, str]], language: str) -> list[dict]:
    user_label = _USER_LABEL.get(language, _USER_LABEL["en"])
    transcript = "\n".join(
        f"{user_label if role == 'user' else 'Samantha'}: {text}"
        for role, text in turns
    )
    return [
        {"role": "system", "content": summarizer_prompt(language)},
        {"role": "user", "content": f"Transcript:\n\n{transcript}"},
    ]


def _build_visual_messages(
    captions: list[tuple[float, str]], language: str
) -> list[dict]:
    # Captions are timestamped (seconds from session start) — keep the
    # timestamps in the prompt so the summarizer can sense the timeline.
    timeline = "\n".join(f"[{ts:6.1f}s] {text}" for ts, text in captions)
    return [
        {"role": "system", "content": visual_summarizer_prompt(language)},
        {"role": "user", "content": f"Scene captions:\n\n{timeline}"},
    ]


async def _call_chat_json(messages: list[dict]) -> dict | None:
    """POST to Chat Completions with response_format=json_object.

    Returns the parsed dict on success, or None on any failure (no api key,
    network error, malformed JSON, etc.). The summarizer is best-effort:
    a failure here just means this session contributes no memory entry.
    """
    if not settings.openai_api_key:
        log.warning("memory: no OPENAI_API_KEY, skipping summary")
        return None

    payload = {
        "model": settings.memory_summarizer_model,
        "messages": messages,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(CHAT_URL, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        raw = data["choices"][0]["message"]["content"]
        return json.loads(raw)
    except Exception:
        log.exception("memory: chat call failed")
        return None


async def summarize(
    turns: list[tuple[str, str]], duration_s: float, language: str = "it"
) -> MemoryEntry | None:
    """Return a MemoryEntry (text track only), or None if not worth saving.

    The visual fields are left empty; the orchestrator merges in the visual
    summary separately when available.
    """
    if len(turns) < 2:
        log.info("memory: session too short (%d turns), skipping summary", len(turns))
        return None

    parsed = await _call_chat_json(_build_messages(turns, language))
    if parsed is None:
        return None

    summary = (parsed.get("summary") or "").strip()
    key_facts = [str(f).strip() for f in parsed.get("key_facts", []) if str(f).strip()]
    if not summary:
        return None

    return MemoryEntry(
        timestamp=now_iso(),
        summary=summary,
        key_facts=key_facts[:5],
        turn_count=len(turns),
        duration_s=round(duration_s, 1),
    )


async def summarize_visual(
    captions: list[tuple[float, str]], language: str = "it"
) -> tuple[str, list[str]]:
    """Return (visual_summary, visual_facts) — empty strings/list on skip.

    Empty result is the orchestrator's signal to leave the visual track
    blank in the assembled MemoryEntry. Reasons we skip:

    * fewer than 3 captions accumulated (too little signal);
    * the chat call failed or returned no usable summary.
    """
    captions = [(ts, t) for ts, t in captions if t and t.strip()]
    if len(captions) < 3:
        log.info("memory: visual track too sparse (%d captions), skipping", len(captions))
        return "", []

    parsed = await _call_chat_json(_build_visual_messages(captions, language))
    if parsed is None:
        return "", []

    visual_summary = (parsed.get("visual_summary") or "").strip()
    raw_facts = parsed.get("visual_facts", [])
    visual_facts = [str(f).strip() for f in raw_facts if str(f).strip()][:3]
    if not visual_summary:
        return "", []
    return visual_summary, visual_facts
