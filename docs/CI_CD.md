# CI / CD

This project uses **GitHub Actions** for free open-source macOS DMGs.

## Why GitHub Actions

| Option | Verdict |
|--------|---------|
| **GitHub Actions (chosen)** | Free for public repos, native `macos-latest` / `macos-13` runners, Releases upload |
| Self-hosted Mac runner | Only needed for Apple notarization with your own hardware/certs |
| Third-party CI | Extra account for little gain here |

Builds are **ad-hoc signed** and clear **quarantine** (`xattr -cr`). Prefer the curl installer (`scripts/install-release.sh`) — curl downloads are not quarantined, so Intel and Apple Silicon installs open cleanly. Full notarization is the only silent double-click for browser DMGs — not used here.

## Pipelines

### 1. `ci.yml` — Validate
- Triggers: push/PR to `main`
- Syntax-check scripts + Python
- Smoke-builds the `.app` / DMG
- Uploads a short-lived artifact

### 2. `release.yml` — Public download
- Triggers: tag `v*` **or** manual “Run workflow”
- Builds installable DMGs (Intel + Apple Silicon)
- Publishes a **GitHub Release** with the DMGs attached

## Cut a release

```bash
git checkout main
git pull
# bump VERSION file first
git tag v1.7.5
git push origin v1.7.5
```

Or: **Actions → Release → Run workflow**.

Users install with:

```bash
curl -fsSL https://raw.githubusercontent.com/Shahzaibzah00r/YouTube-Downloader/main/scripts/install-release.sh | bash
```

Or download from: https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest

## Everyday push

```bash
git add -A
git commit -m "Your message"
git push -u origin main
```
