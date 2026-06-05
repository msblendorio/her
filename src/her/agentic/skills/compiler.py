"""Convert a raw event trace into a runnable AppleScript via the LLM.

Strategy: send the model the user-given name + description, an ordered
list of events (clicks + named-key shortcuts) tagged with app/window
context, and the screenshots taken at each event. Ask for an AppleScript
that prefers high-level commands and only falls back to raw coordinate
clicks when no semantic anchor is available.

The model used is ``settings.skills_compiler_model`` (default
``gpt-4o-mini``). It must be vision-capable: we send screenshots inline
as data URLs.
"""
from __future__ import annotations

import base64
import logging

from ...config import settings
from ...reasoning.text_backend import chat_json
from .recorder import SkillEvent, SkillRecording

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You convert recorded macOS UI interactions into a single AppleScript "
    "that reproduces the same intent. You receive:\n"
    "- A user-given skill name and (optional) description.\n"
    "- An ordered list of low-level events: clicks (x, y, button) and "
    "modifier-key shortcuts (e.g. cmd+s), each tagged with the foreground "
    "app and focused window title at the time.\n"
    "- A screenshot taken right before each event so you can read button "
    "labels and identify UI elements by name.\n"
    "\n"
    "RULES:\n"
    "1. Prefer high-level commands (`tell application \"X\" to ...`) over "
    "raw clicks at coordinates. Coordinates are brittle and will break "
    "the next time the user re-arranges windows.\n"
    "2. When you must use System Events, click UI elements by name/role "
    "(`click button \"Send\" of window 1`, etc.) inferred from the "
    "screenshots — NEVER use absolute coordinates if a label is readable.\n"
    "3. Only fall back to `click at {x, y}` if there is no readable "
    "anchor at all.\n"
    "4. Add short `delay` calls (0.2-0.5s) between steps that wait on UI.\n"
    "5. The script must be self-contained and start by activating the "
    "right app.\n"
    "6. Return EXACTLY a JSON object with the shape:\n"
    '   {"script": "...AppleScript source...", '
    '"summary": "one-line description of what the script does"}\n'
    "No markdown, no code fences, no commentary."
)


async def compile_to_applescript(rec: SkillRecording) -> tuple[str, str] | None:
    """Return ``(script, summary)`` for the recording, or ``None`` on
    failure (no API key, network error, malformed reply, empty trace).
    """
    if not rec.events:
        log.info("skills: empty trace, nothing to compile")
        return None

    # Vision-capable call: in local mode it must hit a multimodal Ollama model
    # (local_llm_vision_model) since the prompt carries screenshots.
    parsed = await chat_json(
        _build_messages(rec),
        cloud_model=settings.skills_compiler_model,
        local_model=settings.local_llm_vision_model,
        temperature=0.2,
        timeout=120.0,
    )
    if not isinstance(parsed, dict):
        return None
    script = (parsed.get("script") or "").strip()
    summary = (parsed.get("summary") or "").strip()
    if not script:
        log.warning("skills: compiler returned an empty script")
        return None
    return script, summary


def _build_messages(rec: SkillRecording) -> list[dict]:
    parts: list[dict] = [{
        "type": "text",
        "text": (
            f"Skill name: {rec.name}\n"
            f"Description: {rec.description or '(none provided)'}\n"
            f"Event count: {len(rec.events)}\n"
            f"---"
        ),
    }]
    for i, evt in enumerate(rec.events, start=1):
        parts.append({"type": "text", "text": _format_event(i, evt)})
        if evt.shot_path:
            try:
                with open(evt.shot_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            except OSError:
                log.debug("skills: skipping missing screenshot %s", evt.shot_path)

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": parts},
    ]


def _format_event(idx: int, e: SkillEvent) -> str:
    mods = ("+".join(e.modifiers) + "+") if e.modifiers else ""
    if e.kind == "click":
        return (
            f"[{idx}] t={e.t:.2f}s {mods}{e.button}-click at ({e.x},{e.y}) "
            f"in app={e.app!r} window={e.window!r}"
        )
    return (
        f"[{idx}] t={e.t:.2f}s {mods}{e.key} "
        f"in app={e.app!r} window={e.window!r}"
    )
