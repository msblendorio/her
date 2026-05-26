#!/usr/bin/env bash
# Build desktop/icon/her.icns from her.jpg.
#
# macOS .icns files are built from an .iconset directory containing PNGs at
# the standard sizes. We center-crop the source to a square, then sips +
# iconutil do the rest.

set -euo pipefail

cd "$(dirname "$0")/.."

SRC="her.jpg"
OUT_DIR="desktop/icon"
ICONSET="$OUT_DIR/her.iconset"
ICNS="$OUT_DIR/her.icns"

if [[ ! -f "$SRC" ]]; then
  echo "ERROR: source image not found: $SRC" >&2
  exit 1
fi

mkdir -p "$ICONSET"

# Center-crop the source to a square at full source resolution.
SRC_W=$(sips -g pixelWidth "$SRC" | awk '/pixelWidth/ {print $2}')
SRC_H=$(sips -g pixelHeight "$SRC" | awk '/pixelHeight/ {print $2}')
SIDE=$(( SRC_W < SRC_H ? SRC_W : SRC_H ))

TMP_SQ="$OUT_DIR/_her_square.png"
# sips inherits the source format unless -s format is set explicitly — without
# this the .png output is silently a JPEG payload and iconutil rejects it.
sips -s format png \
  --cropToHeightWidth "$SIDE" "$SIDE" "$SRC" --out "$TMP_SQ" >/dev/null

# Required iconset entries.
for spec in \
  "16:icon_16x16.png" \
  "32:icon_16x16@2x.png" \
  "32:icon_32x32.png" \
  "64:icon_32x32@2x.png" \
  "128:icon_128x128.png" \
  "256:icon_128x128@2x.png" \
  "256:icon_256x256.png" \
  "512:icon_256x256@2x.png" \
  "512:icon_512x512.png" \
  "1024:icon_512x512@2x.png"
do
  size="${spec%%:*}"
  name="${spec##*:}"
  sips -s format png -z "$size" "$size" "$TMP_SQ" --out "$ICONSET/$name" >/dev/null
done

rm -f "$TMP_SQ"

iconutil -c icns "$ICONSET" -o "$ICNS"
echo "Wrote $ICNS"
