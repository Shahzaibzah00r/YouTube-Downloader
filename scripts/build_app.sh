#!/usr/bin/env bash
# Build an installable macOS .app + .dmg for Intel and Apple Silicon.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
RELEASES="$ROOT/releases"
APP_NAME="Shahzaib YouTube Downloader"
EXEC_NAME="Shahzaib YouTube Downloader"
APP="$DIST/$APP_NAME.app"
ICON_SRC="$ROOT/Youtube Downloader/Assets.xcassets/AppIcon.appiconset/icon_512x512.png"
VERSION="1.1.0"

echo "==> Building $APP_NAME.app ($VERSION)"
rm -rf "$DIST"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$RELEASES"

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

cp "$ROOT/youtube_downloader_gui.py" "$APP/Contents/Resources/youtube_downloader_gui.py"

cat > "$APP/Contents/MacOS/$EXEC_NAME" <<'LAUNCH'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUI="$ROOT/Resources/youtube_downloader_gui.py"

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
  osascript -e 'display dialog "Python 3 with tkinter is required.\n\nInstall Xcode Command Line Tools or Homebrew Python, then try again." buttons {"OK"} default button 1 with title "Shahzaib YouTube Downloader"'
  exit 1
fi

if ! command -v yt-dlp >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    osascript -e 'display notification "Installing yt-dlp and ffmpeg…" with title "Shahzaib YouTube Downloader"'
    brew install yt-dlp ffmpeg || true
  fi
fi

exec "$PYTHON" "$GUI"
LAUNCH
chmod +x "$APP/Contents/MacOS/$EXEC_NAME"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Shahzaib YouTube Downloader</string>
  <key>CFBundleDisplayName</key>
  <string>Shahzaib YouTube Downloader</string>
  <key>CFBundleIdentifier</key>
  <string>com.shahzaibzah00r.youtubedownloader</string>
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
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
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
Shahzaib YouTube Downloader for macOS (Intel + Apple Silicon)

1. Drag "Shahzaib YouTube Downloader" into Applications
2. Open it from Launchpad / Applications
3. If macOS blocks it: Right-click → Open → Open
4. Use the Dark/Light toggle in the app (or Cmd+D)
5. If tools are missing, click "Fix tools" (needs Homebrew)

by Shahzaib — https://github.com/Shahzaibzah00r/YouTube-Downloader
EOF

hdiutil create -volname "Shahzaib YouTube Downloader" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

# Publishable copy for GitHub downloads
cp "$DMG" "$RELEASES/YouTube-Downloader-macOS.dmg"
echo "$VERSION" > "$RELEASES/VERSION.txt"
cat > "$RELEASES/README.md" <<EOF
# Downloads

| File | Description |
|------|-------------|
| [YouTube-Downloader-macOS.dmg](./YouTube-Downloader-macOS.dmg) | Installable app (Intel + Apple Silicon) |

**Version:** $VERSION  
**Author:** Shahzaib ([@Shahzaibzah00r](https://github.com/Shahzaibzah00r))

Install: open the DMG → drag into Applications.
EOF

xattr -cr "$APP" 2>/dev/null || true

echo
echo "✅ App:  $APP"
echo "✅ DMG:  $DMG"
echo "✅ Release copy: $RELEASES/YouTube-Downloader-macOS.dmg"
ls -lh "$APP" "$DMG" "$RELEASES/YouTube-Downloader-macOS.dmg"
