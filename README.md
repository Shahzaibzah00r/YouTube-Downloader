# Shahzaib YouTube Downloader

Free macOS YouTube downloader by **Shahzaib** — works on **Intel** and **Apple Silicon**.

**Repo:** https://github.com/Shahzaibzah00r/YouTube-Downloader  
**Download (DMG):** https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest

## Free download (installable)

1. Open the latest [Release](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest)
2. Download **`YouTube-Downloader-macOS.dmg`**
3. Open the DMG → drag **Shahzaib YouTube Downloader** into **Applications**
4. First launch: Right-click → **Open** if macOS blocks it
5. If tools are missing, click **Fix tools** (needs [Homebrew](https://brew.sh))

Direct DMG link (latest on `main`):

https://github.com/Shahzaibzah00r/YouTube-Downloader/raw/main/releases/YouTube-Downloader-macOS.dmg

## Install from source

```bash
git clone git@github.com-personal:Shahzaibzah00r/YouTube-Downloader.git
# or HTTPS:
git clone https://github.com/Shahzaibzah00r/YouTube-Downloader.git
cd YouTube-Downloader
./install.sh
```

## Features

- Dark & light mode (toggle in the app, or ⌘D) — remembers your choice
- Paste link → choose quality → Download
- Progress bar + live activity log
- Quality: Best / 1080p / 720p / 480p / Audio MP3
- Intel (`x86_64`) + Apple Silicon (`arm64`)
- One-click **Fix tools** for `yt-dlp` + `ffmpeg`

## Build the DMG yourself

```bash
./scripts/build_app.sh
open dist/YouTube-Downloader-macOS.dmg
```

## CLI

```bash
./setup.sh
./download.sh "https://www.youtube.com/watch?v=VIDEO_ID"
./download.sh "https://www.youtube.com/watch?v=VIDEO_ID" ~/Desktop 720
```

## Requirements

- macOS 13+
- Homebrew (for `yt-dlp` / `ffmpeg`)
- Python 3 with tkinter (macOS / Command Line Tools)

## Credits

Maintained by **Shahzaib** ([@Shahzaibzah00r](https://github.com/Shahzaibzah00r)).  
Original SwiftUI inspiration: [jadhavsharad/Youtube-Downloader](https://github.com/jadhavsharad/Youtube-Downloader).  
See [CREDITS.md](./CREDITS.md).

## License

MIT — see [LICENSE](./LICENSE).
