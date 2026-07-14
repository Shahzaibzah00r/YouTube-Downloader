# Shahzaib YouTube Downloader

[![CI](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/ci.yml)
[![Release](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/release.yml/badge.svg)](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/release.yml)
[![Latest release](https://img.shields.io/github/v/release/Shahzaibzah00r/YouTube-Downloader?label=download)](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest)

Free macOS YouTube downloader by **Shahzaib** — works on **Intel** and **Apple Silicon**.

**Repo:** https://github.com/Shahzaibzah00r/YouTube-Downloader

## Free download (installable)

1. Open the latest **[Release](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest)**
2. Download **`YouTube-Downloader-macOS.dmg`**
3. Open the DMG → drag **Shahzaib YouTube Downloader** into **Applications**
4. First launch: Right-click → **Open** if macOS blocks it
5. If tools are missing, click **Fix tools** (needs [Homebrew](https://brew.sh))

> Builds are produced by GitHub Actions on every version tag — no manual DMG upload required.

## Features

- Dark & light mode (toggle or ⌘D) — remembers your choice
- Paste link → choose quality → Download
- Progress bar + live activity log
- Quality: Best / 1080p / 720p / 480p / Audio MP3
- Intel (`x86_64`) + Apple Silicon (`arm64`)
- One-click **Fix tools** for `yt-dlp` + `ffmpeg`

## CI/CD (how releases work)

| Event | Pipeline | Result |
|-------|----------|--------|
| Push / PR | **CI** | Lint + smoke-build DMG (downloadable Actions artifact) |
| Tag `v*` (e.g. `v1.2.0`) | **Release** | Build DMG → publish GitHub Release for everyone |

### Publish a new version

```bash
git tag v1.2.0
git push origin v1.2.0
# GitHub Actions builds the DMG and creates the Release automatically
```

Or: **Actions → Release → Run workflow** and enter a version.

## Install from source

```bash
git clone git@github.com-personal:Shahzaibzah00r/YouTube-Downloader.git
# or: git clone https://github.com/Shahzaibzah00r/YouTube-Downloader.git
cd YouTube-Downloader
./install.sh
```

### Build the DMG locally

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
