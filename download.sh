#!/usr/bin/env bash
# Cross-architecture CLI downloader (Intel x86_64 + Apple Silicon arm64)
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

die() { echo "Error: $*" >&2; exit 1; }

command -v yt-dlp >/dev/null 2>&1 || die "yt-dlp not found. Run ./setup.sh"
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg not found. Run ./setup.sh"

URL="${1:-}"
OUT_DIR="${2:-$HOME/Downloads}"
QUALITY="${3:-best}"

if [[ -z "$URL" ]]; then
  cat <<'EOF'
Usage: ./download.sh <youtube-url> [output-dir] [quality]

  quality: best | 1080 | 720 | 480 | audio

Examples:
  ./download.sh "https://www.youtube.com/watch?v=jNQXAC9IVRw"
  ./download.sh "https://www.youtube.com/watch?v=jNQXAC9IVRw" ~/Desktop 720
  ./download.sh "https://www.youtube.com/playlist?list=PLxxx" ~/Downloads audio
EOF
  exit 1
fi

mkdir -p "$OUT_DIR"
FFMPEG_DIR="$(dirname "$(command -v ffmpeg)")"

case "$QUALITY" in
  audio)
    FORMAT_ARGS=(-f "bestaudio/best" --extract-audio --audio-format mp3 --audio-quality 192k)
    ;;
  1080|720|480)
    FORMAT_ARGS=(-f "bestvideo[height<=${QUALITY}]+bestaudio/best" --merge-output-format mp4)
    ;;
  best|*)
    FORMAT_ARGS=(-f "bv*+ba/b")
    ;;
esac

echo "Arch: $(uname -m)"
echo "Saving to: $OUT_DIR"
yt-dlp \
  --newline \
  --progress \
  --ffmpeg-location "$FFMPEG_DIR" \
  -o "$OUT_DIR/%(title)s.%(ext)s" \
  "${FORMAT_ARGS[@]}" \
  "$URL"

echo "Done."
