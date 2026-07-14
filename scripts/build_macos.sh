#!/usr/bin/env bash
# Build native macOS app for the current Mac (or universal when possible).
# Requires full Xcode (not only Command Line Tools).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! xcodebuild -version >/dev/null 2>&1; then
  echo "Full Xcode is required. Install from the Mac App Store, then:"
  echo "  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
  exit 1
fi

ARCH="$(uname -m)"
CONFIG="${1:-Release}"
DERIVED="$ROOT/build"

echo "Building $CONFIG for host arch: $ARCH"
rm -rf "$DERIVED"

xcodebuild \
  -project "Youtube Downloader.xcodeproj" \
  -scheme "Youtube Downloader" \
  -configuration "$CONFIG" \
  -derivedDataPath "$DERIVED" \
  -arch "$ARCH" \
  CODE_SIGN_IDENTITY="-" \
  CODE_SIGNING_ALLOWED=YES \
  build

APP="$(/usr/bin/find "$DERIVED/Build/Products" -name "Youtube Downloader.app" -type d | head -1)"
if [[ -z "$APP" ]]; then
  echo "Build finished but .app not found under $DERIVED"
  exit 1
fi

OUT="$ROOT/dist"
mkdir -p "$OUT"
rm -rf "$OUT/Youtube Downloader.app"
cp -R "$APP" "$OUT/"

echo
echo "✅ Built: $OUT/Youtube Downloader.app"
file "$OUT/Youtube Downloader.app/Contents/MacOS/"* || true
echo "Open with: open \"$OUT/Youtube Downloader.app\""
