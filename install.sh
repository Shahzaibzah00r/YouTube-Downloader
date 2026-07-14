#!/usr/bin/env bash
# Install YTDownloader (Intel or Apple Silicon).
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="YTDownloader"
DEST="/Applications/$APP_NAME.app"

echo "==> YTDownloader installer"
echo "    CPU: $(uname -m)"

if ! command -v brew >/dev/null 2>&1; then
  echo "==> Installing Homebrew…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ "$(uname -m)" == "arm64" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    eval "$(/usr/local/bin/brew shellenv)"
  fi
fi

if [[ -x /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

echo "==> Installing yt-dlp + ffmpeg"
brew install yt-dlp ffmpeg

if [[ ! -d "$ROOT/dist/$APP_NAME.app" ]]; then
  echo "==> Building application bundle…"
  bash "$ROOT/scripts/build_app.sh"
fi

echo "==> Installing to $DEST"
rm -rf "$DEST"
cp -R "$ROOT/dist/$APP_NAME.app" "$DEST"
xattr -cr "$DEST" 2>/dev/null || true

echo
echo "✅ Installed: $DEST"
open "$DEST"
echo "A dark web UI will open in your browser."
