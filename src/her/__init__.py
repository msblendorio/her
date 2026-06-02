"""her: a 'Her'-style multimodal assistant."""
from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path


def _version_from_yaml() -> str | None:
    """Read the version from the repo-root ``version.yaml`` if present.

    ``version.yaml`` is the single source of truth. It lives at the repo root
    when running from source, and is shipped into the bundle as a resource by
    ``desktop/setup_app.py``, so we read it directly rather than trusting
    possibly-stale install metadata. If it can't be found we fall back to the
    package metadata in ``__version__`` below.
    """
    # From source ``parents[2]`` is the repo root. In the packaged app the file
    # ships as a resource in one of the package's ancestor dirs (py2app drops it
    # under ``Contents/Resources``), so walk every ancestor of this file plus
    # the cwd and take the first ``version.yaml`` we find.
    here = Path(__file__).resolve()
    for base in (*here.parents, Path.cwd()):
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
