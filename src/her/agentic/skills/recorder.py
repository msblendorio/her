"""Global keyboard/mouse event recorder for skill learning.

A pynput listener is spawned in its own thread when recording starts.
We capture two categories of events:

* **Clicks** — left/right/middle button press (down only). Coordinates,
  any modifiers held at that moment, the foreground app, and the focused
  window title are recorded. A small full-screen snapshot is saved next
  to the trace so the compiler can read on-screen labels with vision.
* **Modifier-key shortcuts** — e.g. Cmd+S, Cmd+Shift+T. Plain typing is
  deliberately not captured for v1 (the user dictates text via voice).

macOS permissions: Accessibility (for event capture) and Screen Recording
(for snapshots). Both surface a one-time TCC dialog on first use.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import ImageGrab

log = logging.getLogger(__name__)


@dataclass
class SkillEvent:
    """One captured low-level event."""
    t: float                                          # seconds since recording start
    kind: str                                         # "click" | "keypress"
    x: int = 0
    y: int = 0
    button: str = ""
    key: str = ""
    modifiers: list[str] = field(default_factory=list)
    app: str = ""
    window: str = ""
    shot_path: str = ""


@dataclass
class SkillRecording:
    name: str
    description: str
    started_at: float
    out_dir: Path
    events: list[SkillEvent] = field(default_factory=list)


# Map pynput Key.* names → canonical modifier identifiers.
_MOD_KEYS: dict[str, str] = {
    "Key.cmd": "cmd", "Key.cmd_l": "cmd", "Key.cmd_r": "cmd",
    "Key.ctrl": "ctrl", "Key.ctrl_l": "ctrl", "Key.ctrl_r": "ctrl",
    "Key.alt": "alt", "Key.alt_l": "alt", "Key.alt_r": "alt",
    "Key.shift": "shift", "Key.shift_l": "shift", "Key.shift_r": "shift",
}


def slugify(name: str) -> str:
    """Turn a free-form skill name into a filesystem-safe slug."""
    s = re.sub(r"\s+", "_", name.strip().lower())
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s or "skill"


def _key_name(key: Any) -> str:
    """Stable string name for a pynput Key/KeyCode."""
    name = getattr(key, "name", None)
    if name:
        return f"Key.{name}"
    char = getattr(key, "char", None)
    if char is not None:
        return char
    return str(key)


def _frontmost_app() -> str:
    """Localized name of the frontmost macOS app, or ''."""
    if sys.platform != "darwin":
        return ""
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(app.localizedName() or "") if app else ""
    except Exception:
        return ""


_WINDOW_SCRIPT = (
    'tell application "System Events" to get title of '
    'first window of (first application process whose frontmost is true)'
)


def _frontmost_window() -> str:
    """Best-effort focused window title, or ''. Times out at 1.5s."""
    if sys.platform != "darwin":
        return ""
    try:
        out = subprocess.run(
            ["osascript", "-e", _WINDOW_SCRIPT],
            capture_output=True, timeout=1.5, text=True,
        )
        return out.stdout.strip()
    except Exception:
        return ""


class SkillRecorder:
    """Single-recording-at-a-time global event recorder.

    `start` and `stop` are called from the asyncio loop (via ``to_thread``
    or directly — they're cheap). The pynput listener runs on its own
    thread; callbacks append events under a short lock.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()
        self._listener_mouse: Any = None
        self._listener_kbd: Any = None
        self._recording: SkillRecording | None = None
        self._modifiers_held: set[str] = set()
        self._shot_counter = 0

    @property
    def active(self) -> bool:
        return self._recording is not None

    def start(self, name: str, description: str = "") -> SkillRecording:
        with self._lock:
            if self._recording is not None:
                raise RuntimeError("a recording is already in progress")
            slug = slugify(name)
            out_dir = self._base_dir / slug
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "shots").mkdir(exist_ok=True)

            self._recording = SkillRecording(
                name=name,
                description=description,
                started_at=time.monotonic(),
                out_dir=out_dir,
            )
            self._modifiers_held.clear()
            self._shot_counter = 0
            self._start_listeners()
            log.info("skills: recording started → %s", slug)
            return self._recording

    def stop(self) -> SkillRecording:
        with self._lock:
            if self._recording is None:
                raise RuntimeError("no recording in progress")
            self._stop_listeners()
            rec = self._recording
            self._recording = None
            log.info("skills: recording stopped (%d events)", len(rec.events))
            return rec

    # Listener plumbing -------------------------------------------------

    def _start_listeners(self) -> None:
        try:
            from pynput import keyboard, mouse  # type: ignore[import-untyped]
        except ImportError as e:
            self._recording = None
            raise RuntimeError(
                "pynput is required for skill recording — install it with "
                "`pip install pynput`"
            ) from e

        self._listener_mouse = mouse.Listener(on_click=self._on_click)
        self._listener_kbd = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener_mouse.start()
        self._listener_kbd.start()

    def _stop_listeners(self) -> None:
        if self._listener_mouse is not None:
            try:
                self._listener_mouse.stop()
            except Exception:
                pass
            self._listener_mouse = None
        if self._listener_kbd is not None:
            try:
                self._listener_kbd.stop()
            except Exception:
                pass
            self._listener_kbd = None

    # Callbacks ---------------------------------------------------------

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        if not pressed or self._recording is None:
            return
        rec = self._recording
        evt = SkillEvent(
            t=time.monotonic() - rec.started_at,
            kind="click",
            x=int(x), y=int(y),
            button=getattr(button, "name", str(button)),
            modifiers=sorted(self._modifiers_held),
            app=_frontmost_app(),
            window=_frontmost_window(),
            shot_path=self._snapshot(rec),
        )
        rec.events.append(evt)

    def _on_press(self, key: Any) -> None:
        if self._recording is None:
            return
        name = _key_name(key)
        if name in _MOD_KEYS:
            self._modifiers_held.add(_MOD_KEYS[name])
            return
        # v1: only record key presses with at least one modifier held —
        # plain typing is out of scope (the user dictates text via voice).
        if not self._modifiers_held:
            return
        rec = self._recording
        evt = SkillEvent(
            t=time.monotonic() - rec.started_at,
            kind="keypress",
            key=name,
            modifiers=sorted(self._modifiers_held),
            app=_frontmost_app(),
            window=_frontmost_window(),
            shot_path=self._snapshot(rec),
        )
        rec.events.append(evt)

    def _on_release(self, key: Any) -> None:
        if self._recording is None:
            return
        name = _key_name(key)
        if name in _MOD_KEYS:
            self._modifiers_held.discard(_MOD_KEYS[name])

    # Screenshot --------------------------------------------------------

    def _snapshot(self, rec: SkillRecording) -> str:
        self._shot_counter += 1
        path = rec.out_dir / "shots" / f"{self._shot_counter:03d}.png"
        try:
            img = ImageGrab.grab()
            # Downscale for token budget; the compiler only needs to read
            # labels and roughly localize, not count pixels.
            if max(img.size) > 1280:
                ratio = 1280 / max(img.size)
                img = img.resize(
                    (int(img.size[0] * ratio), int(img.size[1] * ratio)),
                )
            img.save(path, "PNG", optimize=True)
            return str(path)
        except Exception:
            log.exception("skills: snapshot failed")
            return ""
