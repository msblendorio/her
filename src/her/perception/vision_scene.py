"""Local Moondream2 captioner running in a background asyncio task.

Moondream2 is a ~2B-param VLM that runs comfortably on Apple Silicon MPS. The
worker pulls the most recent webcam frame at a fixed cadence, produces a short
caption, and hands it to a callback (typically the orchestrator, which forwards
it to the Realtime session).

Heavy model inference runs in a thread via `asyncio.to_thread` so it never
blocks the event loop.
"""
from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import Awaitable, Callable

from ..config import settings
from ..core.event_bus import bus
from ..core.state import state
from .vision_capture import frame_buffer

log = logging.getLogger(__name__)

CaptionCallback = Callable[[str], Awaitable[None]]


DEFAULT_SCENE_PROMPT = (
    "Describe what is happening in this image in one short sentence, "
    "as if narrating it to a friend on a phone call."
)


class MoondreamCaptioner:
    """Lazy-loaded Moondream2 wrapper. Use the module-level `get_captioner()`
    instead of constructing this directly — the model is large and should be
    loaded only once per process.
    """

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = settings.vision_device
        if device == "mps" and not torch.backends.mps.is_available():
            log.warning("MPS requested but not available, falling back to CPU")
            device = "cpu"

        log.info("loading Moondream model %s on %s ...", settings.vision_model_id, device)
        self._tokenizer = AutoTokenizer.from_pretrained(
            settings.vision_model_id, trust_remote_code=True
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            settings.vision_model_id,
            trust_remote_code=True,
            dtype=torch.float16 if device != "cpu" else torch.float32,
        ).to(device)
        self._device = device
        log.info("Moondream ready")

    def caption(self, image, prompt: str | None = None) -> str:
        self._load()
        assert self._model is not None and self._tokenizer is not None
        try:
            # Moondream's high-level helper. The exact API can vary across
            # checkpoints; this matches `vikhyatk/moondream2` recent revisions.
            enc = self._model.encode_image(image)
            text = self._model.answer_question(enc, prompt or DEFAULT_SCENE_PROMPT, self._tokenizer)
            return text.strip()
        except Exception:
            log.exception("Moondream inference failed")
            return ""


_captioner: MoondreamCaptioner | None = None


def get_captioner() -> MoondreamCaptioner:
    """Process-wide singleton — shared by the periodic vision loop and any
    on-demand consumer (e.g. the agentic `look_at_screen` tool)."""
    global _captioner
    if _captioner is None:
        _captioner = MoondreamCaptioner()
    return _captioner


async def run_vision_loop(on_caption: CaptionCallback) -> None:
    if not settings.vision_enabled:
        log.info("vision disabled (VISION_ENABLED=false)")
        return

    captioner = get_captioner()
    interval = settings.vision_caption_interval
    last_caption_ts = 0.0

    log.info("vision worker started (interval=%.1fs)", interval)
    try:
        while True:
            await asyncio.sleep(0.5)
            frame, ts = await frame_buffer.latest()
            if frame is None or ts <= last_caption_ts:
                continue
            if monotonic() - last_caption_ts < interval:
                continue

            state.seeing = True
            bus.publish("realtime.status", state.snapshot())
            caption = await asyncio.to_thread(captioner.caption, frame)
            state.seeing = False
            last_caption_ts = monotonic()

            if caption:
                state.last_caption = caption
                state.last_caption_at = last_caption_ts
                bus.publish("vision.caption", caption)
                bus.publish("realtime.status", state.snapshot())
                try:
                    await on_caption(caption)
                except Exception:
                    log.exception("on_caption callback failed")
    except asyncio.CancelledError:
        log.info("vision worker cancelled")
        raise
