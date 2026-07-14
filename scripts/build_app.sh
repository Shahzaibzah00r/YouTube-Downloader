#!/usr/bin/env bash
# Build an installable macOS .app (+ optional .dmg) for Intel and Apple Silicon.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
APP_NAME="YouTube Downloader"
APP="$DIST/$APP_NAME.app"
ICON_SRC="$ROOT/Youtube Downloader/Assets.xcassets/AppIcon.appiconset/icon_512x512.png"
VERSION="1.0.0"

echo "==> Building $APP_NAME.app"
rm -rf "$DIST"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Icon
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

# Bundle GUI source
cp "$ROOT/youtube_downloader_gui.py" "$APP/Contents/Resources/youtube_downloader_gui.py"

# Launcher — works when double-clicked from /Applications
cat > "$APP/Contents/MacOS/YouTube Downloader" <<'LAUNCH'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUI="$ROOT/Resources/youtube_downloader_gui.py"

# Prefer Homebrew Python if present (better tk), else system Python 3
PYTHON=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
  if [[ -x "$candidate" ]]; then
    if "$candidate" -c "import tkinter" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  osascript -e 'display dialog "Python 3 with tkinter is required.\n\nInstall Xcode Command Line Tools or Homebrew Python, then try again." buttons {"OK"} default button 1 with title "YouTube Downloader"'
  exit 1
fi

# Auto-install tools on first launch if missing
if ! command -v yt-dlp >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    osascript -e 'display notification "Installing yt-dlp and ffmpeg…" with title "YouTube Downloader"'
    brew install yt-dlp ffmpeg || true
  fi
fi

exec "$PYTHON" "$GUI"
LAUNCH
chmod +x "$APP/Contents/MacOS/YouTube Downloader"

# Info.plist
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>YouTube Downloader</string>
  <key>CFBundleDisplayName</key>
  <string>YouTube Downloader</string>
  <key>CFBundleIdentifier</key>
  <string>com.shahzaibzah00r.youtubedownloader</string>
  <key>CFBundleVersion</key>
  <string>$VERSION</string>
  <key>CFBundleShortVersionString</key>
  <string>$VERSION</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>YouTube Downloader</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

# PkgInfo
echo -n "APPL????" > "$APP/Contents/PkgInfo"

# Copy install helper next to app
cp "$ROOT/install.sh" "$DIST/install.sh" 2>/dev/null || true
chmod +x "$DIST/install.sh" 2>/dev/null || true

# Create DMG
DMG="$DIST/YouTube-Downloader-macOS.dmg"
STAGE="$DIST/dmg-stage"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/README.txt" <<EOF
YouTube Downloader for macOS (Intel + Apple Silicon)

1. Drag "YouTube Downloader" into Applications
2. Open it from Launchpad / Applications
3. If macOS blocks it: Right-click → Open → Open
4. On first use, click "Fix tools" if prompted (needs Homebrew)

https://github.com/Shahzaibzah00r/YouTube-Downloader
EOF

hdiutil create -volname "YouTube Downloader" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

# Clear quarantine on local build
xattr -cr "$APP" 2>/dev/null || true

echo
echo "✅ App:  $APP"
echo "✅ DMG:  $DMG"
ls -lh "$APP" "$DMG"
file "$APP/Contents/MacOS/YouTube Downloader"
