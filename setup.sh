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

echo "==> Setting up Python app window (pywebview)"
ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
  if [[ -x "$candidate" ]]; then PYTHON="$candidate"; break; fi
done
"$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -U pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"

echo
echo "✅ Setup complete on $ARCH"
echo "   yt-dlp:  $(command -v yt-dlp)"
echo "   ffmpeg:  $(command -v ffmpeg)"
echo "   python:  $ROOT/.venv/bin/python"
echo
echo "Run the app window:"
echo "  \"$ROOT/.venv/bin/python\" \"$ROOT/yt_downloader.py\""
echo "  # or"
echo "  open \"$ROOT/Open YTDownloader.command\""
