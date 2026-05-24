"""Holds the latest webcam frame received from the browser.

The browser grabs frames via `<canvas>.toBlob('image/jpeg')` and ships them
through a dedicated WebSocket. We keep only the most recent one — the captioner
samples it at its own cadence.
"""
from __future__ import annotations

import asyncio
import io
import logging
from time import monotonic

from PIL import Image

log = logging.getLogger(__name__)


class FrameBuffer:
    def __init__(self) -> None:
        self._frame: Image.Image | None = None
        self._ts: float = 0.0
        self._lock = asyncio.Lock()

    async def put_jpeg(self, jpeg: bytes) -> None:
        try:
            img = Image.open(io.BytesIO(jpeg)).convert("RGB")
        except Exception:
            log.warning("invalid jpeg frame, dropping")
            return
        async with self._lock:
            self._frame = img
            self._ts = monotonic()

    async def latest(self) -> tuple[Image.Image | None, float]:
        async with self._lock:
            return self._frame, self._ts


frame_buffer = FrameBuffer()
