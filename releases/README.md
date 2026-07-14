# Downloads

Official installable builds are published by **GitHub Actions** on every version tag.

## Get the app

➡️ **[Latest Release](https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest)**

Download `YouTube-Downloader-macOS.dmg`, open it, drag **Shahzaib YouTube Downloader** into Applications.

## How releases are built (CI/CD)

| Trigger | What happens |
|---------|----------------|
| Push / PR to `main` | CI validates scripts + smoke-builds a DMG (artifact, 14 days) |
| Push tag `v1.2.0` (or Actions → Release → Run workflow) | Builds DMG + publishes a GitHub Release anyone can download |

```bash
# Cut a new public release
git tag v1.2.0
git push origin v1.2.0
```

Author: **Shahzaib** ([@Shahzaibzah00r](https://github.com/Shahzaibzah00r))
