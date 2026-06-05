"""Forge a runnable AppleScript from a *spoken description* of a skill.

This is the text-only sibling of :mod:`compiler` (Skill Forge). Where the
recorder/compiler path turns a demonstration (clicks + screenshots) into a
script, here the user simply *describes* what they want in natural language
and we ask the LLM to author the equivalent AppleScript directly — no trace,
no screenshots.

The product is identical (an AppleScript saved into the same ``SkillStore``),
so a forged skill is invoked by ``run_skill`` and surfaced in the prompt
exactly like a demonstrated one.

The model used is ``settings.skills_forge_model`` (default ``gpt-4o-mini``).
It only ever sees text, so it need not be vision-capable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ...config import settings
from ...reasoning.text_backend import chat_json

log = logging.getLogger(__name__)


@dataclass
class ForgeResult:
    """Outcome of forging a description into a script.

    ``warnings`` lists any steps the model was unsure it could reliably
    automate; they are surfaced in the preview so the user can judge before
    confirming.
    """
    script: str
    summary: str
    warnings: list[str] = field(default_factory=list)


_SYSTEM_PROMPT = (
    "You author a single macOS AppleScript that accomplishes the action a "
    "user describes in plain language. You receive a user-given skill name, "
    "a free-form description of what the skill should do, and optionally a "
    "correction from a previous attempt.\n"
    "\n"
    "RULES:\n"
    "1. Prefer high-level commands (`tell application \"X\" to ...`) over raw "
    "clicks at coordinates. Coordinates are brittle.\n"
    "2. When you must use System Events, click UI elements by name/role "
    "(`click button \"Send\" of window 1`, etc.) — NEVER absolute "
    "coordinates if a label exists.\n"
    "3. Add short `delay` calls (0.2-0.5s) between steps that wait on UI.\n"
    "4. The script must be self-contained and start by activating the right "
    "app.\n"
    "5. Do NOT invent capabilities. If part of the description cannot be done "
    "reliably in AppleScript, OMIT it from the script and add a short note to "
    "`warnings` explaining what you skipped and why.\n"
    "6. If essentially NONE of the description can be automated in "
    "AppleScript, return an empty `script` and explain in `warnings`.\n"
    "7. Return EXACTLY a JSON object with the shape:\n"
    '   {"script": "...AppleScript source...", '
    '"summary": "one-line plain-language description of what the script '
    'does", "warnings": ["...", ...]}\n'
    "No markdown, no code fences, no commentary."
)


async def forge_to_applescript(
    name: str,
    description: str,
    feedback: str | None = None,
) -> ForgeResult | None:
    """Turn ``name`` + ``description`` into a :class:`ForgeResult`.

    Returns ``None`` on failure (no API key, network error, malformed reply,
    or a model that produced no usable script). ``feedback`` carries a user
    correction from a previous attempt so the call can be refined.
    """
    description = (description or "").strip()
    if not description:
        log.info("forge: empty description, nothing to compile")
        return None

    parsed = await chat_json(
        _build_messages(name, description, feedback),
        cloud_model=settings.skills_forge_model,
        local_model=settings.local_llm_model,
        temperature=0.2,
        timeout=120.0,
    )
    if not isinstance(parsed, dict):
        return None
    script = (parsed.get("script") or "").strip()
    summary = (parsed.get("summary") or "").strip()
    warnings = parsed.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    warnings = [str(w).strip() for w in warnings if str(w).strip()]
    if not script:
        log.warning("forge: model returned an empty script for %r", name)
        return None
    return ForgeResult(script=script, summary=summary, warnings=warnings)


def _build_messages(name: str, description: str, feedback: str | None) -> list[dict]:
    user = (
        f"Skill name: {name}\n"
        f"Description: {description}"
    )
    if feedback:
        user += f"\n\nCorrection to apply to your previous attempt: {feedback}"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
