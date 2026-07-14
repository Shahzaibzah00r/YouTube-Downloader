# Publish checklist (Shahzaib)

Remote:

```bash
git remote set-url origin git@github.com-personal:Shahzaibzah00r/YouTube-Downloader.git
```

## Everyday push

```bash
git add -A
git commit -m "Your message"
git push -u origin main
# CI runs automatically
```

## Public downloadable build (recommended)

```bash
git tag v1.2.0
git push origin v1.2.0
# Release workflow builds DMG and attaches it to the GitHub Release
```

Or: **Actions → Release → Run workflow**.

Users download from: https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest

See [docs/CI_CD.md](./docs/CI_CD.md).
