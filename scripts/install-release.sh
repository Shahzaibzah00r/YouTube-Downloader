#!/usr/bin/env bash
# Install latest YTDownloader release WITHOUT Gatekeeper quarantine.
# Browser DMG downloads get com.apple.quarantine; curl does not.
#
# Usage (Intel or Apple Silicon — auto-detected):
#   curl -fsSL https://raw.githubusercontent.com/Shahzaibzah00r/YouTube-Downloader/main/scripts/install-release.sh | bash
#
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:$PATH"

REPO="Shahzaibzah00r/YouTube-Downloader"
DEST="/Applications/YTDownloader.app"
TMPDIR="${TMPDIR:-/tmp}/ytdownloader-install-$$"
mkdir -p "$TMPDIR"
MOUNT=""
cleanup() {
  rm -rf "$TMPDIR"
  if [[ -n "${MOUNT:-}" ]]; then
    hdiutil detach "$MOUNT" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64) LABEL="AppleSilicon" ;;
  *)             LABEL="Intel" ;;
esac

echo "==> YTDownloader installer ($LABEL / $ARCH)"
echo "    Fetching latest release…"

API="https://api.github.com/repos/${REPO}/releases/latest"
JSON="$(curl -fsSL -H "Accept: application/vnd.github+json" -H "User-Agent: YTDownloader-Installer" "$API")"
TAG="$(printf '%s' "$JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("tag_name",""))')"
ASSET_URL="$(printf '%s' "$JSON" | LABEL="$LABEL" python3 -c '
import sys, json, os
label = os.environ.get("LABEL", "Intel")
data = json.load(sys.stdin)
for a in data.get("assets") or []:
    n = a.get("name") or ""
    if n.endswith(".dmg") and label in n:
        print(a.get("browser_download_url") or "")
        raise SystemExit
for a in data.get("assets") or []:
    n = a.get("name") or ""
    if n.endswith(".dmg"):
        print(a.get("browser_download_url") or "")
        raise SystemExit
')"

if [[ -z "$ASSET_URL" ]]; then
  echo "ERROR: No DMG found on latest release."
  exit 1
fi

DMG="$TMPDIR/YTDownloader.dmg"
echo "==> Downloading $TAG ($LABEL)…"
# curl does NOT set com.apple.quarantine — Gatekeeper stays quiet
curl -fL --progress-bar -o "$DMG" "$ASSET_URL"

echo "==> Mounting…"
ATTACH_OUT="$(hdiutil attach -nobrowse -readonly "$DMG")"
MOUNT="$(printf '%s\n' "$ATTACH_OUT" | awk '/\/Volumes\//{print $NF; exit}')"
if [[ -z "$MOUNT" || ! -d "$MOUNT" ]]; then
  echo "ERROR: Could not mount DMG"
  exit 1
fi

SRC="$(find "$MOUNT" -maxdepth 1 -name "*.app" -print -quit)"
if [[ -z "$SRC" || ! -d "$SRC" ]]; then
  echo "ERROR: No .app in DMG"
  exit 1
fi

echo "==> Closing any running YTDownloader…"
osascript >/dev/null 2>&1 <<'EOF' || true
tell application "System Events"
  try
    set ids to unix id of every process whose bundle identifier is "com.shahzaibzah00r.ytdownloader"
    repeat with pid in ids
      do shell script "kill -9 " & pid
    end repeat
  end try
end tell
EOF
pkill -9 -f "YTDownloader.app/Contents" 2>/dev/null || true
pkill -9 -f "Contents/Resources/yt_downloader.py" 2>/dev/null || true
for p in $(seq 8765 8784); do
  lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
done
sleep 0.4

echo "==> Installing to $DEST"
rm -rf "$DEST"
xattr -cr "$SRC" 2>/dev/null || true
ditto "$SRC" "$DEST"
xattr -cr "$DEST" 2>/dev/null || true
xattr -d com.apple.quarantine "$DEST" 2>/dev/null || true
codesign --force --deep --sign - "$DEST" 2>/dev/null || true
xattr -cr "$DEST" 2>/dev/null || true

hdiutil detach "$MOUNT" >/dev/null 2>&1 || true
MOUNT=""

echo "==> Opening YTDownloader $TAG"
open "$DEST"
echo "✅ Done — installed without browser quarantine."
