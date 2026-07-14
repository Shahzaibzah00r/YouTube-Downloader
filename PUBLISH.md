# Publish checklist for https://github.com/shahzaibzah00r/Youtube-Downloader

## Create / push

```bash
cd "/Users/shahz/Documents/Shahzaib/Youtube-Downloader"

git remote rename origin upstream 2>/dev/null || true
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/shahzaibzah00r/Youtube-Downloader.git

git add -A
git commit -m "Release dual-arch installable YouTube Downloader"
git push -u origin main
```

## Build release assets

```bash
./scripts/build_app.sh
# upload dist/YouTube-Downloader-macOS.dmg to a GitHub Release
```

## Tag a release

```bash
git tag v1.0.0
git push origin v1.0.0
```
