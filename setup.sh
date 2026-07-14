#!/usr/bin/env bash
# Install dependencies for Intel (x86_64) and Apple Silicon (arm64) Macs.
set -euo pipefail

echo "==> YouTube Downloader setup"
ARCH="$(uname -m)"
case "$ARCH" in
  arm64)  echo "Detected: Apple Silicon (arm64)";;
  x86_64) echo "Detected: Intel (x86_64)";;
  *)      echo "Detected: $ARCH";;
esac

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Installing…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ "$ARCH" == "arm64" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    eval "$(/usr/local/bin/brew shellenv)"
  fi
fi

# Ensure brew is on PATH in this shell
if [[ -x /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

echo "==> Installing yt-dlp and ffmpeg"
brew install yt-dlp ffmpeg

echo "==> Making scripts executable"
ROOT="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$ROOT/download.sh" \
         "$ROOT/setup.sh" \
         "$ROOT/youtube_downloader_gui.py" \
         "$ROOT/Open YouTube Downloader.command" \
         "$ROOT/scripts/build_macos.sh" 2>/dev/null || true

echo
echo "✅ Setup complete on $ARCH"
echo "   yt-dlp:  $(command -v yt-dlp)"
echo "   ffmpeg:  $(command -v ffmpeg)"
echo "   ffprobe: $(command -v ffprobe)"
echo
echo "Run the easy GUI:"
echo "  open \"$ROOT/Open YouTube Downloader.command\""
echo "  # or"
echo "  python3 \"$ROOT/youtube_downloader_gui.py\""
echo
echo "CLI:"
echo "  \"$ROOT/download.sh\" \"https://www.youtube.com/watch?v=VIDEO_ID\""
echo
echo "Native Swift UI (requires full Xcode):"
echo "  open \"$ROOT/Youtube Downloader.xcodeproj\""
