# Publish to personal GitHub (Shahzaibzah00r)

Remote (matches your SSH config Host `github.com-personal`):

```bash
git remote set-url origin git@github.com-personal:Shahzaibzah00r/YouTube-Downloader.git
```

```bash
./scripts/build_app.sh
git add -A
git commit -m "Release Shahzaib YouTube Downloader with DMG"
git push -u origin main

# Optional GitHub Release (after: gh auth login — personal account)
gh release create v1.1.0 releases/YouTube-Downloader-macOS.dmg \
  --title "v1.1.0 — Shahzaib YouTube Downloader" \
  --notes "Installable DMG for Intel + Apple Silicon. Dark/light mode included."
```

Public DMG on main:

https://github.com/Shahzaibzah00r/YouTube-Downloader/raw/main/releases/YouTube-Downloader-macOS.dmg
