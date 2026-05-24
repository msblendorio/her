"""On-demand screen capture.

Two flavors are exposed:

* `look_at_screen(question)` — Moondream2 *captioner*. Good for "what app is
  in focus?" or "describe what I'm looking at" — paraphrases the screen.
* `read_screen(language)` — Apple Vision OCR. Returns the *verbatim* text on
  screen. This is what accessibility mode uses to actually read content to a
  visually impaired user.

macOS note: both paths shell out to `/usr/sbin/screencapture`, which requires
Screen Recording permission for the parent process (Terminal / PyCharm / the
python binary). The first call may surface a system dialog.
"""
from __future__ import annotations

import asyncio
import logging

from PIL import Image, ImageGrab

from ..perception.vision_scene import get_captioner
from .ocr import OCRUnavailable, ocr_screen
from .registry import tool

log = logging.getLogger(__name__)

# Moondream is fine with smaller images and noticeably faster on them.
_MAX_SIDE = 1280

# Hard cap on returned OCR text to keep token cost predictable and keep
# Samantha from droning on. Anything longer gets truncated with a marker.
_OCR_MAX_CHARS = 4000

_DEFAULT_PROMPT = (
    "Briefly describe what is currently shown on this computer screen. "
    "Focus on the active app, the page or document, and any text the user is reading or editing. "
    "Ignore generic OS chrome like the menu bar."
)


def _grab() -> Image.Image:
    img = ImageGrab.grab()  # macOS: defaults to the main display
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > _MAX_SIDE:
        ratio = _MAX_SIDE / max(img.size)
        img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
    return img


@tool()
async def look_at_screen(question: str = "") -> str:
    """Take a screenshot of the user's screen RIGHT NOW and describe what is on it.
    Use this whenever the user asks what is on their screen, asks for help with what
    they are reading or editing, or any time the answer depends on the current visible
    content. You can pass an optional `question` to ask Moondream a specific thing
    (e.g. 'what error message is visible?', 'which app is in focus?').
    This is NOT the webcam — that one already streams to you continuously.

    Args:
        question: Optional specific question about the screen content.
    """
    img = await asyncio.to_thread(_grab)
    prompt = (question or "").strip() or _DEFAULT_PROMPT
    caption = await asyncio.to_thread(get_captioner().caption, img, prompt)
    if not caption:
        raise RuntimeError("Moondream returned an empty caption")
    return caption


@tool()
async def read_screen(language: str = "") -> str:
    """Read the user's screen with Apple Vision OCR and return the verbatim text.
    Prefer this over look_at_screen whenever the user needs the exact wording —
    reading an email, a button label, an error message, a paragraph — and ALWAYS
    in accessibility mode. Returns plain text (one line per recognized region).
    Local, on-device, no network.

    Args:
        language: Optional BCP-47-ish hint ('it', 'en', 'es', 'fr', 'de'). Improves OCR accuracy.
    """
    try:
        text = await ocr_screen(language=language)
    except OCRUnavailable as e:
        log.warning("OCR unavailable, falling back to Moondream: %s", e)
        return await look_at_screen("Read the text currently visible on this screen verbatim.")

    text = text.strip()
    if not text:
        return ""
    if len(text) > _OCR_MAX_CHARS:
        text = text[:_OCR_MAX_CHARS] + "\n…[truncated]"
    return text
