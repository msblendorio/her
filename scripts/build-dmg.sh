#!/usr/bin/env bash
# Build Her.app and wrap it into a drag-to-Applications DMG.
#
# Prereqs (one-time):
#   brew install create-dmg
#   python3.13 -m venv .venv
#   source .venv/bin/activate
#   pip install -e ".[desktop]"
#
# Usage:
#   ./scripts/build-dmg.sh                # build everything
#   ./scripts/build-dmg.sh --app-only     # stop after py2app
#   ./scripts/build-dmg.sh --dmg-only     # only rebuild the DMG from existing dist/Her.app
#
# Output: dist/Her-<version>.dmg

set -euo pipefail

cd "$(dirname "$0")/.."

APP_NAME="Her"
APP_BUNDLE="dist/${APP_NAME}.app"
VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')"
DMG_PATH="dist/${APP_NAME}-${VERSION}.dmg"

MODE="all"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-only) MODE="app"; shift ;;
    --dmg-only) MODE="dmg"; shift ;;
    -h|--help)
      sed -n '2,/^$/s/^# //p' "$0"
      exit 0
      ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# ── Preflight ────────────────────────────────────────────────────────
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: this script only runs on macOS." >&2
  exit 1
fi

if [[ "$MODE" != "dmg" ]]; then
  if ! python -c "import py2app" 2>/dev/null; then
    echo "ERROR: py2app not found. Run: pip install -e \".[desktop]\"" >&2
    exit 1
  fi
fi

if [[ "$MODE" != "app" ]]; then
  if ! command -v create-dmg >/dev/null 2>&1; then
    echo "ERROR: create-dmg not found. Run: brew install create-dmg" >&2
    exit 1
  fi
fi

# ── Icon ─────────────────────────────────────────────────────────────
if [[ "$MODE" != "dmg" ]]; then
  if [[ ! -f desktop/icon/her.icns ]]; then
    echo "==> Generating app icon"
    ./scripts/make-icon.sh
  fi
fi

# ── py2app ───────────────────────────────────────────────────────────
if [[ "$MODE" != "dmg" ]]; then
  echo "==> Cleaning previous build"
  rm -rf build "$APP_BUNDLE" desktop/build desktop/dist

  echo "==> Building Her.app with py2app (this takes a few minutes)"
  # Run from desktop/ so setuptools doesn't pick up the root pyproject.toml —
  # its [project].dependencies gets translated to install_requires, which
  # setuptools 78+ refuses to accept inside a setup() call.
  ( cd desktop && python setup_app.py py2app \
      --dist-dir ../dist \
      --bdist-base ../build )

  if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "ERROR: py2app did not produce $APP_BUNDLE" >&2
    exit 1
  fi

  # ── Ad-hoc codesign ────────────────────────────────────────────────
  # Without this, Gatekeeper rejects the bundled .dylibs even after the
  # user clears the quarantine xattr. Ad-hoc signing (-) is free and
  # works for personal / unsigned distribution.
  #
  # NB: do NOT pass --options runtime here. Hardened Runtime requires
  # every dlopen'd library to share the loading process's Team ID; with
  # ad-hoc signing the bundled Python.framework keeps its original
  # python.org Team ID and macOS refuses to load it ("mapping process
  # and mapped file (non-platform) have different Team IDs").
  echo "==> Ad-hoc signing $APP_BUNDLE"
  codesign --force --deep --sign - \
    --timestamp=none \
    "$APP_BUNDLE" || {
      echo "WARN: codesign failed; continuing with unsigned bundle." >&2
    }
fi

if [[ "$MODE" == "app" ]]; then
  echo
  echo "App built: $APP_BUNDLE"
  echo "To run:    open \"$APP_BUNDLE\""
  exit 0
fi

# ── DMG ──────────────────────────────────────────────────────────────
if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "ERROR: $APP_BUNDLE not found. Build it first (drop --dmg-only)." >&2
  exit 1
fi

echo "==> Building $DMG_PATH"
rm -f "$DMG_PATH"

CREATE_DMG_ARGS=(
  --volname "${APP_NAME} installer"
  --window-size 540 380
  --icon-size 100
  --icon "${APP_NAME}.app" 138 225
  --hide-extension "${APP_NAME}.app"
  --app-drop-link 402 225
  --no-internet-enable
)

if [[ -f desktop/icon/her.icns ]]; then
  CREATE_DMG_ARGS+=(--volicon "desktop/icon/her.icns")
fi

create-dmg "${CREATE_DMG_ARGS[@]}" "$DMG_PATH" "$APP_BUNDLE"

echo
echo "===== Build complete ====="
echo "  App: $APP_BUNDLE"
echo "  DMG: $DMG_PATH"
echo
echo "First launch from a fresh download will be blocked by Gatekeeper because"
echo "the bundle is unsigned. Right-click Her.app > Open to bypass that once."
