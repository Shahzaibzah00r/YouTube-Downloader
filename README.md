# YTDownloader

[![CI](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/ci.yml)
[![Release](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/release.yml/badge.svg)](https://github.com/Shahzaibzah00r/YouTube-Downloader/actions/workflows/release.yml)
[![Latest release](https://img.shields.io/github/v/release/Shahzaibzah00r/YouTube-Downloader?label=download)](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest)

Free macOS YouTube downloader — **Intel** and **Apple Silicon**.  
Dark web UI (HTML/CSS) in your browser — reliable and easy to use.

**Repo:** https://github.com/Shahzaibzah00r/YouTube-Downloader

## Run now

```bash
git clone https://github.com/Shahzaibzah00r/YouTube-Downloader.git
cd YouTube-Downloader
./setup.sh          # once: brew install yt-dlp ffmpeg
python3 yt_downloader.py
```

Opens **http://127.0.0.1:8765/** with a dark UI.  
Or double-click **`Open YTDownloader.command`**.

## Free download (installable DMG)

1. Open the latest **[Release](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest)**
2. Download the DMG that matches your Mac:

| Your Mac | File name |
|----------|-----------|
| **Intel** MacBook / iMac | `YTDownloader-…-**Intel**-macOS.dmg` |
| **Apple Silicon** M1 / M2 / **M3** / M4 | `YTDownloader-…-**AppleSilicon**-macOS.dmg` |

Not sure? Apple menu → **About This Mac** (Chip = Intel or M1/M2/M3/M4).

3. Drag **YTDownloader** into **Applications**
4. Open it — the dark web UI launches in your browser
5. If tools are missing, click **Fix tools** ([Homebrew](https://brew.sh))

## Features

- Dark web UI (default)
- Paste link → quality → Download
- Live progress + activity log
- Best / 1080p / 720p / 480p / Audio MP3
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
git tag v1.3.0
git push origin v1.3.0
```

## Credits

Created and maintained by **Shahzaib** ([@Shahzaibzah00r](https://github.com/Shahzaibzah00r)).  
See [CREDITS.md](./CREDITS.md).

## License

MIT — see [LICENSE](./LICENSE).
