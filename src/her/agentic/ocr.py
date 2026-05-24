"""Apple Vision OCR — accurate, on-device text recognition from the screen.

Used by accessibility mode to *read* what is on screen (verbatim) rather than
paraphrase it the way Moondream does. Runs entirely locally via the Vision
framework (pyobjc), no network, no extra weights to download.

Falls back with a clear error if Vision is unavailable (non-macOS, or
pyobjc-framework-Vision not installed). Callers should treat OCR as optional
and degrade to `look_at_screen` (Moondream) when this raises.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import subprocess
import sys
import tempfile

log = logging.getLogger(__name__)

# Prefix used for every temp PNG we write. Kept as a constant so the
# startup sweep below can find and remove orphans left behind by a hard
# crash (SIGKILL, panic) between screencapture and the os.unlink in the
# finally clause of ocr_screen().
_TMP_PREFIX = "her_ocr_"


class OCRUnavailable(RuntimeError):
    """Raised when Apple Vision OCR cannot run on this machine."""


def _sweep_orphans() -> int:
    """Remove any her_ocr_*.png files left in $TMPDIR by a previous run.

    Cheap — runs once at import time, only globs our own prefix.
    """
    removed = 0
    pattern = os.path.join(tempfile.gettempdir(), f"{_TMP_PREFIX}*.png")
    for path in glob.glob(pattern):
        try:
            os.unlink(path)
            removed += 1
        except OSError:
            pass
    if removed:
        log.info("OCR: cleaned up %d orphan temp screenshot(s)", removed)
    return removed


_sweep_orphans()


def _check_platform() -> None:
    if sys.platform != "darwin":
        raise OCRUnavailable("Apple Vision OCR is only available on macOS")


def _import_vision():
    try:
        import Vision  # noqa: F401
        from Foundation import NSURL  # noqa: F401
        return Vision, NSURL
    except ImportError as e:
        raise OCRUnavailable(
            "pyobjc-framework-Vision is not installed (pip install pyobjc-framework-Vision)"
        ) from e


# Map our short language codes to BCP-47 tags Vision understands.
_LANG_TAGS: dict[str, str] = {
    "it": "it-IT",
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
}


def _screencapture_to_tempfile() -> str:
    fd, path = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=".png")
    os.close(fd)
    try:
        subprocess.run(
            ["screencapture", "-x", path],
            check=True,
            timeout=10,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        os.unlink(path)
        raise OCRUnavailable(
            f"screencapture failed (Screen Recording permission?): "
            f"{e.stderr.decode(errors='replace').strip()}"
        ) from e
    except subprocess.TimeoutExpired as e:
        os.unlink(path)
        raise OCRUnavailable("screencapture timed out") from e
    return path


def _ocr_file_sync(path: str, language: str = "") -> str:
    Vision, NSURL = _import_vision()

    url = NSURL.fileURLWithPath_(path)
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    # Accurate is slower but worth it for UI text; we already throttle.
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)

    tag = _LANG_TAGS.get((language or "").lower()[:2])
    if tag:
        request.setRecognitionLanguages_([tag, "en-US"])

    success, error = handler.performRequests_error_([request], None)
    if not success:
        raise OCRUnavailable(f"Vision OCR failed: {error}")

    observations = request.results() or []
    # Sort top-to-bottom, then left-to-right. Vision's coordinates are
    # bottom-left origin and normalized to [0, 1], so a higher Y means higher
    # on screen → we want descending Y for natural reading order.
    def _key(obs):
        box = obs.boundingBox()
        return (-round(float(box.origin.y), 2), float(box.origin.x))

    observations = sorted(observations, key=_key)

    lines: list[str] = []
    for obs in observations:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        text = str(candidates[0].string()).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def is_available() -> bool:
    """Best-effort availability probe — does not actually run OCR."""
    if sys.platform != "darwin":
        return False
    try:
        _import_vision()
        return True
    except OCRUnavailable:
        return False


async def ocr_screen(language: str = "") -> str:
    """Capture the current screen and return the recognized text verbatim.

    Raises OCRUnavailable on platforms / installs that can't run Vision OCR.
    """
    _check_platform()
    _import_vision()  # fail fast before screencapture if pyobjc is missing

    path = await asyncio.to_thread(_screencapture_to_tempfile)
    try:
        text = await asyncio.to_thread(_ocr_file_sync, path, language)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return text
