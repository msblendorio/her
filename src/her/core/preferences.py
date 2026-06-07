"""Persistent user preferences across sessions.

Currently tracks only the accessibility flag — but kept as a tiny key/value
JSON so adding future knobs (preferred voice, default language override,
…) doesn't need new plumbing.

Writes are atomic: temp file in the same directory + `os.replace`, so a
crash mid-write cannot corrupt the existing file.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


_AST_MODES = ("off", "prompt", "lora_shadow", "lora_primary")


@dataclass
class Preferences:
    accessibility: bool = False
    # Pulse (ambient proactive check-in). Off by default — proactive speech is
    # opt-in. Interval is seconds between ticks. See core/scheduler.py.
    pulse_enabled: bool = False
    pulse_interval_s: float = 180.0
    # AST — Auto Self-Training. These are the privacy-sensitive live switches:
    # they persist across sessions like accessibility so the user's choice
    # sticks, and they default OFF so nothing is ever learned/recorded without
    # an explicit opt-in. `ast_enabled` is the master switch; `ast_capture` is
    # the separate opt-in to persist raw turns (T1); `ast_mode` selects how the
    # local student participates. See src/her/ast/ and AST_MODE_PLAN.md.
    ast_enabled: bool = False
    ast_capture: bool = False
    ast_mode: str = "off"   # see _AST_MODES

    def to_dict(self) -> dict:
        return {
            "accessibility": bool(self.accessibility),
            "pulse_enabled": bool(self.pulse_enabled),
            "pulse_interval_s": float(self.pulse_interval_s),
            "ast_enabled": bool(self.ast_enabled),
            "ast_capture": bool(self.ast_capture),
            "ast_mode": self.ast_mode if self.ast_mode in _AST_MODES else "off",
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Preferences":
        mode = str(d.get("ast_mode", "off") or "off")
        return cls(
            accessibility=bool(d.get("accessibility", False)),
            pulse_enabled=bool(d.get("pulse_enabled", False)),
            pulse_interval_s=float(d.get("pulse_interval_s", 180.0) or 180.0),
            ast_enabled=bool(d.get("ast_enabled", False)),
            ast_capture=bool(d.get("ast_capture", False)),
            ast_mode=mode if mode in _AST_MODES else "off",
        )


class PreferencesStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> Preferences:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Preferences()
        except OSError:
            log.warning("preferences: could not read %s", self.path)
            return Preferences()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("preferences: %s is not valid JSON — starting empty", self.path)
            return Preferences()
        if not isinstance(data, dict):
            return Preferences()
        return Preferences.from_dict(data)

    def save(self, prefs: Preferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".prefs_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(prefs.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
