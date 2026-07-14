#!/usr/bin/env bash
# Build an installable macOS .app + .dmg for YTDownloader (web UI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
RELEASES="$ROOT/releases"
APP_NAME="YTDownloader"
EXEC_NAME="YTDownloader"
APP="$DIST/$APP_NAME.app"
ICON_SRC="$ROOT/assets/AppIcon.png"

if [[ -n "${VERSION:-}" ]]; then
  :
elif [[ -n "${1:-}" ]]; then
  VERSION="$1"
elif [[ -f "$ROOT/VERSION" ]]; then
  VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
elif git -C "$ROOT" describe --tags --exact-match 2>/dev/null | grep -q .; then
  VERSION="$(git -C "$ROOT" describe --tags --exact-match)"
elif git -C "$ROOT" describe --tags --always 2>/dev/null | grep -q .; then
  VERSION="$(git -C "$ROOT" describe --tags --always)"
else
  VERSION="1.7.6"
fi
VERSION_TAG="$VERSION"
VERSION="${VERSION#v}"

echo "==> Building $APP_NAME.app ($VERSION_TAG)"
rm -rf "$DIST"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/webui" "$RELEASES"

if [[ -f "$ICON_SRC" ]]; then
  mkdir -p "$DIST/icon.iconset"
  sips -z 16 16     "$ICON_SRC" --out "$DIST/icon.iconset/icon_16x16.png" >/dev/null
  sips -z 32 32     "$ICON_SRC" --out "$DIST/icon.iconset/icon_16x16@2x.png" >/dev/null
  sips -z 32 32     "$ICON_SRC" --out "$DIST/icon.iconset/icon_32x32.png" >/dev/null
  sips -z 64 64     "$ICON_SRC" --out "$DIST/icon.iconset/icon_32x32@2x.png" >/dev/null
  sips -z 128 128   "$ICON_SRC" --out "$DIST/icon.iconset/icon_128x128.png" >/dev/null
  sips -z 256 256   "$ICON_SRC" --out "$DIST/icon.iconset/icon_128x128@2x.png" >/dev/null
  sips -z 256 256   "$ICON_SRC" --out "$DIST/icon.iconset/icon_256x256.png" >/dev/null
  sips -z 512 512   "$ICON_SRC" --out "$DIST/icon.iconset/icon_256x256@2x.png" >/dev/null
  sips -z 512 512   "$ICON_SRC" --out "$DIST/icon.iconset/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$ICON_SRC" --out "$DIST/icon.iconset/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$DIST/icon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
  rm -rf "$DIST/icon.iconset"
fi

# Bundle web UI + server
cp "$ROOT/yt_downloader.py" "$APP/Contents/Resources/yt_downloader.py"
cp "$ROOT/webui/index.html" "$ROOT/webui/styles.css" "$ROOT/webui/app.js" "$APP/Contents/Resources/webui/"
# Version file for in-app update checks
printf '%s\n' "$VERSION" > "$APP/Contents/Resources/VERSION"
printf '%s\n' "$VERSION" > "$ROOT/VERSION"

cat > "$APP/Contents/MacOS/$EXEC_NAME" <<'LAUNCH'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP_BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
RES="$HERE/Resources"
LOGDIR="$HOME/Library/Logs/YTDownloader"
LOG="$LOGDIR/launch.log"
mkdir -p "$LOGDIR"
cd "$RES"

exec >>"$LOG" 2>&1
echo "---- $(date) launch $(uname -m) ----"

# Clear Gatekeeper quarantine on every launch (unsigned OSS — no paid Apple cert)
xattr -cr "$APP_BUNDLE" 2>/dev/null || true
codesign --force --deep --sign - "$APP_BUNDLE" 2>/dev/null || true
xattr -cr "$APP_BUNDLE" 2>/dev/null || true

# Prefer Homebrew Python on Apple Silicon (arm64) over /usr/local (often Rosetta)
PYTHON=""
ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]]; then
  CANDIDATES=(/opt/homebrew/bin/python3 /usr/bin/python3 /usr/local/bin/python3)
else
  CANDIDATES=(/usr/local/bin/python3 /usr/bin/python3 /opt/homebrew/bin/python3)
fi
for candidate in "${CANDIDATES[@]}"; do
  if [[ -x "$candidate" ]]; then PYTHON="$candidate"; break; fi
done

if [[ -z "$PYTHON" ]]; then
  osascript -e 'display dialog "Python 3 is required.\n\nInstall from python.org or: brew install python" buttons {"OK"} default button 1 with title "YTDownloader"'
  exit 1
fi
echo "python=$PYTHON"

# App-local venv for pywebview (native Mac window, not browser)
VENV="$HOME/Library/Application Support/YTDownloader/venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  osascript -e 'display notification "Setting up YTDownloader (first launch)…" with title "YTDownloader"'
  mkdir -p "$(dirname "$VENV")"
  if ! "$PYTHON" -m venv "$VENV"; then
    osascript -e 'display dialog "Could not create the app environment.\n\nTry: brew install python\nThen reopen YTDownloader." buttons {"OK"} default button 1 with title "YTDownloader"'
    exit 1
  fi
  "$VENV/bin/pip" install -U pip || true
  if ! "$VENV/bin/pip" install pywebview; then
    osascript -e 'display dialog "Could not install pywebview (needed for the Mac window).\n\nCheck your internet connection and reopen the app.\nLog: ~/Library/Logs/YTDownloader/launch.log" buttons {"OK"} default button 1 with title "YTDownloader"'
    rm -rf "$VENV"
    exit 1
  fi
fi

# Do NOT block the window on brew install — that made first launch look "broken"
# (brew can take minutes). Open the app; user can click Fix tools inside.
if ! command -v yt-dlp >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1; then
  osascript -e 'display notification "Open the app → click Fix tools to install yt-dlp & ffmpeg" with title "YTDownloader"' || true
fi

exec "$VENV/bin/python" yt_downloader.py
LAUNCH
chmod +x "$APP/Contents/MacOS/$EXEC_NAME"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>YTDownloader</string>
  <key>CFBundleDisplayName</key>
  <string>YTDownloader</string>
  <key>CFBundleIdentifier</key>
  <string>com.shahzaibzah00r.ytdownloader</string>
  <key>CFBundleVersion</key>
  <string>$VERSION</string>
  <key>CFBundleShortVersionString</key>
  <string>$VERSION</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>$EXEC_NAME</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

echo -n "APPL????" > "$APP/Contents/PkgInfo"

# Architecture label for download filenames
# Override with ARCH_LABEL=Intel|AppleSilicon (CI builds both names on one fast runner)
HOST_ARCH="$(uname -m)"
if [[ -n "${ARCH_LABEL:-}" ]]; then
  case "$ARCH_LABEL" in
    AppleSilicon|Intel) ;;
    *) echo "Unknown ARCH_LABEL=$ARCH_LABEL"; exit 1 ;;
  esac
else
  case "$HOST_ARCH" in
    arm64|aarch64) ARCH_LABEL="AppleSilicon" ;;
    x86_64|amd64)  ARCH_LABEL="Intel" ;;
    *)             ARCH_LABEL="$HOST_ARCH" ;;
  esac
fi

case "$ARCH_LABEL" in
  AppleSilicon) ARCH_FRIENDLY="Apple Silicon (M1 / M2 / M3 / M4)" ;;
  Intel)        ARCH_FRIENDLY="Intel Mac (x86_64)" ;;
  *)            ARCH_FRIENDLY="$ARCH_LABEL" ;;
esac

# Ad-hoc sign BEFORE packaging (Gatekeeper still warns on download without notarization,
# but signing + Install script below avoids the “blocked” loop for most users).
xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP" 2>/dev/null || true
xattr -cr "$APP" 2>/dev/null || true

DMG_GENERIC="$DIST/YouTube-Downloader-macOS.dmg"
DMG_ARCH="$DIST/YTDownloader-v${VERSION}-${ARCH_LABEL}-macOS.dmg"
STAGE="$DIST/dmg-stage"
rm -rf "$STAGE" "$DMG_GENERIC" "$DMG_ARCH"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

# First-run helper: clears quarantine then opens (macOS re-quarantines GitHub downloads)
cat > "$STAGE/Install & Open.command" <<'INSTALL'
#!/bin/bash
set -e
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/YTDownloader.app"
DEST="/Applications/YTDownloader.app"

if [[ ! -d "$SRC" ]]; then
  osascript -e 'display dialog "YTDownloader.app not found next to this installer." buttons {"OK"} default button 1 with title "YTDownloader"'
  exit 1
fi

osascript -e 'display notification "Installing YTDownloader…" with title "YTDownloader"' || true

# Close any already-running copy first (process name is often Python, not YTDownloader)
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
pkill -9 -f "YTDownloader.app/Contents/MacOS/YTDownloader" >/dev/null 2>&1 || true
pkill -9 -f "YTDownloader.app/Contents/Resources/yt_downloader.py" >/dev/null 2>&1 || true
pkill -9 -f "/Applications/YTDownloader.app" >/dev/null 2>&1 || true
for p in $(seq 8765 8784); do
  lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
done
sleep 0.4

rm -rf "$DEST"
# Clear quarantine on the DMG copy before install (browsers quarantine the whole volume)
xattr -cr "$SRC" 2>/dev/null || true
xattr -d com.apple.quarantine "$SRC" 2>/dev/null || true

if command -v ditto >/dev/null 2>&1; then
  ditto "$SRC" "$DEST"
else
  cp -R "$SRC" "$DEST"
fi

# Remove the “downloaded from internet” flag — this is what blocks open
xattr -cr "$DEST" 2>/dev/null || true
xattr -d com.apple.quarantine "$DEST" 2>/dev/null || true
codesign --force --deep --sign - "$DEST" 2>/dev/null || true
xattr -cr "$DEST" 2>/dev/null || true

open "$DEST"
osascript -e 'display notification "YTDownloader is ready" with title "YTDownloader"' || true
INSTALL
chmod +x "$STAGE/Install & Open.command"

cat > "$STAGE/README.txt" <<EOF
YTDownloader for macOS — $ARCH_FRIENDLY

RECOMMENDED (no Gatekeeper quarantine):
  curl -fsSL https://raw.githubusercontent.com/Shahzaibzah00r/YouTube-Downloader/main/scripts/install-release.sh | bash
  (curl download is not quarantined; works on Intel and Apple Silicon)

From this DMG:
  1. Double-click “Install & Open.command”
  2. If Terminal asks, click Open
  3. App installs to Applications and opens (quarantine cleared)

If you only dragged the .app and see “Apple could not verify…”:
    xattr -cr /Applications/YTDownloader.app
    open /Applications/YTDownloader.app

Or: System Settings → Privacy & Security → Open Anyway

Which DMG (if downloading manually)?
  • YTDownloader-…-Intel-macOS.dmg         → Intel MacBook / iMac
  • YTDownloader-…-AppleSilicon-macOS.dmg → M1 / M2 / M3 / M4 Macs

This build: $ARCH_FRIENDLY ($HOST_ARCH)

https://github.com/Shahzaibzah00r/YouTube-Downloader
EOF

# No spaces in volname — keeps /Volumes paths easy for installers/parsers
hdiutil create -volname "YTDownloader-${ARCH_LABEL}" -srcfolder "$STAGE" -ov -format UDZO "$DMG_ARCH" >/dev/null
# Also keep a classic filename for backwards compatibility
cp "$DMG_ARCH" "$DMG_GENERIC"
rm -rf "$STAGE"

mkdir -p "$RELEASES"
cp "$DMG_ARCH" "$RELEASES/" 2>/dev/null || true
cp "$DMG_GENERIC" "$RELEASES/YouTube-Downloader-macOS.dmg" 2>/dev/null || true
echo "$VERSION" > "$RELEASES/VERSION.txt"
echo "$ARCH_LABEL" > "$RELEASES/ARCH.txt"

xattr -cr "$DMG_ARCH" 2>/dev/null || true
xattr -cr "$DMG_GENERIC" 2>/dev/null || true

echo
echo "✅ App:   $APP"
echo "✅ DMG:   $DMG_ARCH"
echo "✅ Also:  $DMG_GENERIC"
echo "   Arch:  $ARCH_FRIENDLY"
echo "   Tip:   curl install-release.sh | bash  (no quarantine) — or Install & Open.command in DMG"
ls -lh "$APP" "$DMG_ARCH" "$DMG_GENERIC"
