"""her: a 'Her'-style multimodal assistant."""
from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path


def _version_from_yaml() -> str | None:
    """Read the version from the repo-root ``version.yaml`` if present.

    ``version.yaml`` is the single source of truth. It lives at the repo root —
    available when running from source — so we read it directly rather than
    trusting possibly-stale install metadata. In a packaged/installed app the
    file is absent and we fall back to the metadata hatchling baked in from the
    very same file at build time.
    """
    # src/her/__init__.py -> parents[2] is the repo root.
    for base in (Path(__file__).resolve().parents[2], Path.cwd()):
        try:
            text = (base / "version.yaml").read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, re.MULTILINE)
        if match:
            return match.group(1)
    return None


__version__ = _version_from_yaml()
if not __version__:
    try:
        __version__ = _pkg_version("her")
    except PackageNotFoundError:  # editable install without metadata
        __version__ = "0.0.0"
