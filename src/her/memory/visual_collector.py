"""Listens on the event bus and accumulates the webcam captions seen during a session.

Mirrors `TranscriptCollector`, but for the visual track. The captions come from
`vision.caption` (produced by the Moondream2 worker in
`perception/vision_scene.py`) and are kept in memory only for the lifetime of
the session — at session-end they are handed to the visual summarizer and
discarded.

Two cheap defenses keep the buffer well-behaved on long sessions:

* duplicate captions back-to-back are dropped (the camera rarely changes
  meaningfully between two ticks);
* a hard FIFO cap (`MAX_CAPTIONS`) protects against runaway memory if the
  user keeps a session open for hours.
"""
from __future__ import annotations

import asyncio
import logging
from time import monotonic

from ..core.event_bus import bus

log = logging.getLogger(__name__)

MAX_CAPTIONS = 200


class VisualCollector:
    def __init__(self) -> None:
        # Each entry is (monotonic_ts_relative_to_start, caption_text).
        self.captions: list[tuple[float, str]] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._started_at: float = 0.0
        self._last_norm: str = ""

    async def start(self) -> None:
        if self._running:
            return
        self.captions.clear()
        self._last_norm = ""
        self._started_at = monotonic()
        self._running = True

        q = bus.subscribe("vision.caption")

        async def pump() -> None:
            try:
                while self._running:
                    caption = await q.get()
                    if not caption:
                        continue
                    text = str(caption).strip()
                    if not text:
                        continue
                    norm = text.lower()
                    if norm == self._last_norm:
                        continue
                    self._last_norm = norm
                    ts = monotonic() - self._started_at
                    self.captions.append((ts, text))
                    # FIFO drop oldest beyond the cap.
                    if len(self.captions) > MAX_CAPTIONS:
                        del self.captions[: len(self.captions) - MAX_CAPTIONS]
            except asyncio.CancelledError:
                raise
            finally:
                bus.unsubscribe("vision.caption", q)

        self._tasks = [asyncio.create_task(pump(), name="memory-collect-vision")]

    async def stop(self) -> list[tuple[float, str]]:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        return list(self.captions)
