# YTDownloader

[![CI](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/ci.yml)
[![Release](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/release.yml/badge.svg)](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/release.yml)
[![Latest release](https://img.shields.io/github/v/release/Shahzaibzah00r/YouTube-Downloader?label=download)](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest)

Free macOS YouTube downloader — **Intel** and **Apple Silicon**.  
Native window with dark / light web UI — reliable and easy to use.

**Repo:** https://github.com/Shahzaibzah00r/YouTube-Downloader

## Run now

```bash
git clone https://github.com/Shahzaibzah00r/YouTube-Downloader.git
cd YouTube-Downloader
./setup.sh                 # once: tools + native window support
./Open\ YTDownloader.command
```

Opens a **real Mac app window** (not the browser).  
Or:

```bash
.venv/bin/python yt_downloader.py
```

## Free download (installable DMG)

1. Open the latest **[Release](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest)**
2. Download the DMG that matches your Mac:

| Your Mac | File name |
|----------|-----------|
| **Intel** MacBook / iMac | `YTDownloader-…-**Intel**-macOS.dmg` |
| **Apple Silicon** M1 / M2 / **M3** / M4 | `YTDownloader-…-**AppleSilicon**-macOS.dmg` |

Not sure? Apple menu → **About This Mac** (Chip = Intel or M1/M2/M3/M4).

3. Drag **YTDownloader** into **Applications**
4. Open it — YTDownloader launches in a native Mac window
5. If tools are missing, click **Fix tools** ([Homebrew](https://brew.sh))

## Features

- Native Mac app window (pywebview) with dark / light theme
- Single + batch URL queue (YouTube, playlists, and direct file links)
- Preview (title / thumbnail) before download
- Video, audio (MP3), or both — video checked by default
- Quality: best / 1080p / 720p / 480p
- Live progress + activity log
- Intel (`x86_64`) + Apple Silicon (`arm64`)
- **Fix tools** installs `yt-dlp` + `ffmpeg`

## Install from source

```bash
./install.sh
```

## CLI

```bash
./download.sh "https://www.youtube.com/watch?v=VIDEO_ID"
./download.sh "https://www.youtube.com/watch?v=VIDEO_ID" ~/Desktop 720
```

## CI/CD

| Event | Result |
|-------|--------|
| Push / PR | Lint + smoke-build DMG |
| Tag `v*` | Build DMG → GitHub Release |

```bash
git tag v1.6.0
git push origin v1.6.0
```

## Credits

Created and maintained by **Shahzaib** ([@Shahzaibzah00r](https://github.com/Shahzaibzah00r)).  
See [CREDITS.md](./CREDITS.md).

## License

MIT — see [LICENSE](./LICENSE).
