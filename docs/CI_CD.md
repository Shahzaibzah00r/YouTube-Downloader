# CI/CD

This project uses **GitHub Actions** (best fit for a free open-source macOS DMG):

## Why GitHub Actions

| Option | Verdict |
|--------|---------|
| **GitHub Actions (chosen)** | Free for public repos, native `macos-latest` runners, built-in Releases upload |
| Self-hosted Mac runner | Only needed for Apple notarization with your own hardware/certs |
| Third-party CI (Circle, etc.) | Extra account for little gain here |

We do **not** notarize with Apple Developer ID in CI (needs paid cert + secrets).  
Builds are **ad-hoc signed** and the app / installer clear **quarantine** (`xattr -cr`) so most Macs open without a Settings trip. Full notarization is the only complete Gatekeeper silence — not used here.

## Pipelines

### 1. `ci.yml` — Validate
- Triggers: push/PR to `main`
- Syntax-check scripts + Python
- Smoke-builds the `.app` / DMG
- Uploads a short-lived artifact

### 2. `release.yml` — Public download
- Triggers: tag `v*` **or** manual “Run workflow”
- Builds the installable DMG on macOS
- Publishes a **GitHub Release** with the DMG attached

## Cut a release

```bash
git checkout main
git pull
git tag v1.2.0
git push origin v1.2.0
```

Then open: https://github.com/Shahzaibzah00r/YouTube-Downloader/releases
