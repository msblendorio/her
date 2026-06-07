"""Shared session state — the UI mirrors these flags as status indicators."""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from .usage import usage


@dataclass
class SessionState:
    active: bool = False
    listening: bool = False  # mic is open & streaming to OpenAI
    thinking: bool = False   # awaiting first audio/text delta from model
    speaking: bool = False   # model is currently streaming audio out
    seeing: bool = False     # vision worker has a fresh frame in flight
    last_caption: str = ""
    last_caption_at: float = 0.0
    started_at: float = 0.0
    # Opt-in mode for visually impaired users: periodic OCR of the screen is
    # injected as context, and the persona is told to read concisely. Toggled
    # by voice via the `toggle_accessibility_mode` tool.
    accessibility: bool = False

    def snapshot(self) -> dict:
        snap = {
            "active": self.active,
            "listening": self.listening,
            "thinking": self.thinking,
            "speaking": self.speaking,
            "seeing": self.seeing,
            "last_caption": self.last_caption,
            "uptime_s": round(monotonic() - self.started_at, 1) if self.started_at else 0.0,
            "usage": usage.snapshot(),
            "accessibility": self.accessibility,
        }
        # AST status for the header badge (off | idle | learning | consolidating
        # | training). Late import keeps core/state free of an import cycle.
        try:
            from ..ast import ast_manager
            snap["ast"] = ast_manager.status()
        except Exception:
            pass
        return snap


state = SessionState()
