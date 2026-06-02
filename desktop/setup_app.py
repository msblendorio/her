"""py2app build script for Her.app.

Usage (from repo root, inside an active venv with `pip install -e .[desktop]`):

    python desktop/setup_app.py py2app

Produces ``dist/Her.app``. Wrapped by ``scripts/build-dmg.sh`` which then
runs ad-hoc codesign and create-dmg.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# py2app's modulegraph recursively walks every imported module's AST. Default
# CPython recursion limit (1000) blows up on torch / transformers internals.
sys.setrecursionlimit(50000)

from setuptools import setup

ROOT = Path(__file__).resolve().parent.parent

# Make `her` importable from src/ without an install step.
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _read_version() -> str:
    """Read the version from version.yaml — the single source of truth."""
    text = (ROOT / "version.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


VERSION = _read_version()

APP = [str(ROOT / "desktop" / "launcher.py")]
ICON = str(ROOT / "desktop" / "icon" / "her.icns")

# Ship the UI as a data resource so the FileResponse in server/app.py
# resolves correctly inside the bundle (it locates static/ relative to
# the her package which lives in Resources/lib).
DATA_FILES = []

PLIST = {
    "CFBundleName": "Her",
    "CFBundleDisplayName": "Her",
    "CFBundleIdentifier": "io.sblendorio.her",
    "CFBundleShortVersionString": VERSION,
    "CFBundleVersion": VERSION,
    "LSMinimumSystemVersion": "12.0",
    "NSHighResolutionCapable": True,
    # Per-capability usage strings. macOS surfaces these in the consent
    # dialog the first time Samantha hits each capability.
    "NSMicrophoneUsageDescription":
        "Her uses the microphone so you can talk to Samantha in real time.",
    "NSCameraUsageDescription":
        "Her uses the webcam to let Samantha see and describe your environment.",
    "NSAppleEventsUsageDescription":
        "Her sends Apple Events to open apps, run Shortcuts, and read Mail and Calendar on your behalf.",
    "NSCalendarsUsageDescription":
        "Her reads and creates events so Samantha can answer questions about your agenda.",
    "NSContactsUsageDescription":
        "Her looks up contacts when you ask Samantha to email or schedule with someone.",
    "NSDesktopFolderUsageDescription":
        "Her saves screenshots to your Desktop when you ask Samantha to capture the screen.",
    "NSSpeechRecognitionUsageDescription":
        "Her uses macOS speech recognition for on-device transcription.",
    # Don't show in the Dock as a background-only app — we want a real
    # window.
    "LSUIElement": False,
}

OPTIONS = {
    "argv_emulation": False,
    "iconfile": ICON,
    "plist": PLIST,
    # Packages whose internals py2app's static analyzer can't fully
    # trace: list them explicitly so all submodules ship.
    "packages": [
        "her",
        "uvicorn",
        "fastapi",
        "starlette",
        "pydantic",
        "pydantic_settings",
        "websockets",
        "httpx",
        "httpcore",
        "h11",
        "certifi",
        "dotenv",
        # Cowork + knowledge wiki. `anthropic` is imported lazily in
        # her.cowork.client, so py2app's static modulegraph never sees it —
        # list it (and its non-stdlib deps) explicitly so it ships.
        "anthropic",
        "distro",
        "jiter",
        # anyio loads its backend modules with importlib.import_module at
        # request time (e.g. "anyio._backends._asyncio"), invisible to
        # py2app's static modulegraph — pull in the whole package.
        "anyio",
        "sniffio",
        "transformers",
        "torch",
        "einops",
        "accelerate",
        "PIL",
        "numpy",
        "ddgs",
        "pynput",
        "webview",
    ],
    "includes": [
        "her.main",
        "her.server.app",
        "her.server.ws",
        "her.agentic",
        "her.agentic.tools",
        "her.agentic.macos",
        "her.agentic.calendar",
        "her.agentic.screen",
        "her.agentic.web",
        "her.agentic.accessibility",
        "her.memory.store",
        "her.perception",
        "her.reasoning",
        "her.voice",
        "her.ui",
    ],
    # Trim the bundle: things we don't use.
    "excludes": [
        "tkinter",
        "test",
        "tests",
        "matplotlib",
        "scipy",
        "pandas",
        "notebook",
        "IPython",
        "jupyter",
    ],
    "resources": [
        str(ROOT / "src" / "her" / "ui"),
        # Ship version.yaml so her.__version__ resolves at runtime inside the
        # bundle (it lands in Contents/Resources, an ancestor of the her
        # package dir, where _version_from_yaml walks up to find it).
        str(ROOT / "version.yaml"),
    ],
    # py2app strips bytecode by default which breaks some pkg_resources
    # lookups — keep .py files.
    "strip": False,
    "optimize": 0,
    "semi_standalone": False,
    # MUST stay False — True leaks the host's site-packages into sys.path,
    # making `import certifi` (and others) resolve to the user's system
    # install instead of the bundled copy. That breaks SSL because the
    # bundled cacert.pem never gets used.
    "site_packages": False,
}

setup(
    app=APP,
    name="Her",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
