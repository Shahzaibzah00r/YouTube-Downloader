#!/usr/bin/env bash
# Build an installable macOS .app + .dmg for YTDownloader (web UI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
RELEASES="$ROOT/releases"
APP_NAME="YTDownloader"
EXEC_NAME="YTDownloader"
APP="$DIST/$APP_NAME.app"
ICON_SRC="$ROOT/Youtube Downloader/Assets.xcassets/AppIcon.appiconset/icon_512x512.png"

if [[ -n "${VERSION:-}" ]]; then
  :
elif [[ -n "${1:-}" ]]; then
  VERSION="$1"
elif git -C "$ROOT" describe --tags --exact-match 2>/dev/null | grep -q .; then
  VERSION="$(git -C "$ROOT" describe --tags --exact-match)"
elif git -C "$ROOT" describe --tags --always 2>/dev/null | grep -q .; then
  VERSION="$(git -C "$ROOT" describe --tags --always)"
else
  VERSION="1.3.0"
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
cp "$ROOT/youtube_downloader_gui.py" "$APP/Contents/Resources/youtube_downloader_gui.py"
cp "$ROOT/webui/index.html" "$ROOT/webui/styles.css" "$ROOT/webui/app.js" "$APP/Contents/Resources/webui/"

cat > "$APP/Contents/MacOS/$EXEC_NAME" <<'LAUNCH'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE/Resources"

PYTHON=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
  if [[ -x "$candidate" ]]; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  osascript -e 'display dialog "Python 3 is required.\n\nInstall Xcode Command Line Tools or Homebrew Python." buttons {"OK"} default button 1 with title "YTDownloader"'
  exit 1
fi

if ! command -v yt-dlp >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    osascript -e 'display notification "Installing yt-dlp and ffmpeg…" with title "YTDownloader"'
    brew install yt-dlp ffmpeg || true
  fi
fi

# Open dark web UI in the browser
exec "$PYTHON" yt_downloader.py
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
cp "$ROOT/install.sh" "$DIST/install.sh" 2>/dev/null || true
chmod +x "$DIST/install.sh" 2>/dev/null || true

DMG="$DIST/YouTube-Downloader-macOS.dmg"
STAGE="$DIST/dmg-stage"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/README.txt" <<EOF
YTDownloader for macOS (Intel + Apple Silicon)

1. Drag YTDownloader into Applications
2. Open it — a dark web UI opens in your browser
3. Paste a YouTube URL and click Download
4. If tools are missing, click Fix tools (needs Homebrew)

https://github.com/Shahzaibzah00r/YouTube-Downloader
EOF

hdiutil create -volname "YTDownloader" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

cp "$DMG" "$RELEASES/YouTube-Downloader-macOS.dmg" 2>/dev/null || true
echo "$VERSION" > "$RELEASES/VERSION.txt"

xattr -cr "$APP" 2>/dev/null || true

echo
echo "✅ App:  $APP"
echo "✅ DMG:  $DMG"
ls -lh "$APP" "$DMG"
