#!/usr/bin/env python3
"""Sync the version from version.yaml into static files that can't read it.

version.yaml is the single source of truth. Code (her.__version__), the
packaging metadata (pyproject + hatchling), the DMG build script, and the
py2app plist all derive the version at import/build time.

README.md is intentionally version-agnostic — it never names a release number
(download links point at /releases/latest, build paths use a `<version>`
placeholder) so it doesn't need bumping. ``TARGETS`` is therefore empty; the
mechanism is kept for any future static file that does embed a literal version.

Usage:
    python scripts/sync_version.py          # rewrite in place
    python scripts/sync_version.py --check   # exit 1 if anything is stale (CI)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_version() -> str:
    text = (ROOT / "version.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, re.MULTILINE)
    if not match:
        sys.exit("version.yaml: no `version:` field found")
    return match.group(1)


# (path, regex with one capture group for the version, replacement template).
# The template uses {v} for the new version. The regex must match the whole
# token so the replacement is unambiguous. Empty by design — see the module
# docstring (README.md is version-agnostic).
TARGETS: list[tuple[str, str, str]] = []


def main() -> int:
    check = "--check" in sys.argv[1:]
    version = read_version()
    stale = False

    for rel, pattern, template in TARGETS:
        path = ROOT / rel
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        updated = re.sub(pattern, template.format(v=version), original)
        if updated != original:
            stale = True
            if check:
                print(f"STALE: {rel} does not match version {version}")
            else:
                path.write_text(updated, encoding="utf-8")
                print(f"updated {rel} -> {version}")

    if check and stale:
        print("Run `python scripts/sync_version.py` to fix.")
        return 1
    if not stale and not check:
        print(f"all files already at {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
