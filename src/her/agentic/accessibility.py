"""Accessibility mode toggle.

Lives in its own module so the delayed ``core.orchestrator`` import stays
out of the macOS / calendar / web tool files. The orchestrator imports
back through ``agentic`` transitively, so we resolve the cycle by deferring
the import to call time.
"""
from __future__ import annotations

from .registry import tool


@tool()
async def toggle_accessibility_mode(on: bool) -> str:
    """Turn the assistant's accessibility mode for visually impaired users ON or OFF.
    When ON: the screen is OCR'd periodically and the text is injected as context,
    and you read it concisely (no robotic descriptions, no bullet lists).
    Call this when the user says things like 'attiva modalità accessibilità',
    'activate accessibility mode', 'help me, I can't see the screen', or the inverse.
    After toggling, say one short sentence confirming the new state.

    Args:
        on: True to enable, false to disable.
    """
    # Late import to avoid a tools <-> core.orchestrator import cycle.
    from ..core.orchestrator import orchestrator

    await orchestrator.set_accessibility(bool(on))
    return "accessibility_on" if on else "accessibility_off"
