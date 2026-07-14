# YouTube Downloader for macOS

Easy YouTube downloader for **Intel** and **Apple Silicon** Macs.

Repo: https://github.com/Shahzaibzah00r/YouTube-Downloader

## Install (recommended)

### Option A — DMG (after a release is published)

1. Download `YouTube-Downloader-macOS.dmg` from [Releases](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases)
2. Open the DMG
3. Drag **YouTube Downloader** into **Applications**
4. Open the app (Right-click → Open the first time if macOS blocks it)
5. If tools are missing, click **Fix tools** inside the app (needs [Homebrew](https://brew.sh))

### Option B — one command from source

```bash
git clone https://github.com/Shahzaibzah00r/YouTube-Downloader.git
cd Youtube-Downloader
./install.sh
```

This installs Homebrew tools (`yt-dlp`, `ffmpeg`), builds the `.app`, and copies it to `/Applications`.

### Option C — DMG from source

```bash
./scripts/build_app.sh
open dist/YouTube-Downloader-macOS.dmg
```

## Features

- Clean, reliable GUI (paste link → download)
- Progress bar + live log
- Quality: Best / 1080p / 720p / 480p / Audio MP3
- Works on Intel (`x86_64`) and Apple Silicon (`arm64`)
- **Fix tools** button installs dependencies automatically

## CLI

```bash
./setup.sh
./download.sh "https://www.youtube.com/watch?v=VIDEO_ID"
./download.sh "https://www.youtube.com/watch?v=VIDEO_ID" ~/Desktop 720
```

## Native SwiftUI app (optional)

Requires full Xcode:

```bash
open "Youtube Downloader.xcodeproj"
# or
./scripts/build_macos.sh
```

## Requirements

- macOS 13+
- Homebrew (installer can guide you)
- Python 3 with tkinter (included with macOS / CLT)

## Credits

Inspired by [jadhavsharad/Youtube-Downloader](https://github.com/jadhavsharad/Youtube-Downloader). See [CREDITS.md](./CREDITS.md).

## License

MIT — see [LICENSE](./LICENSE).
