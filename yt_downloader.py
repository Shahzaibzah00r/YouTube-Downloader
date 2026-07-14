#!/usr/bin/env python3
"""YTDownloader — native desktop app (HTML UI inside a Mac window)."""

from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
WEBUI = ROOT / "webui"
HOST = "127.0.0.1"
PORT = 8765
ACTIVE_PORT = PORT
DEFAULT_DIR = str(Path.home() / "Downloads")
HISTORY_PATH = Path.home() / ".ytdownloader" / "history.json"
HISTORY_MAX = 20
GITHUB_REPO = "Shahzaibzah00r/YouTube-Downloader"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
# Bump when cutting a release (also written into the .app by build_app.sh)
APP_VERSION_FALLBACK = "1.7.6"
PROGRESS_RE = re.compile(r"\[download\]\s+([0-9.]+)%")
SPEED_RE = re.compile(
    r"at\s+([0-9.]+)\s*([KMGT]?i?B)/s",
    re.IGNORECASE,
)
ETA_RE = re.compile(r"ETA\s+(\d+):(\d+)(?::(\d+))?")
DEST_RE = re.compile(
    r'(?:Destination:\s+|Merging formats into\s+")([^"\n]+)"?',
    re.IGNORECASE,
)
FILENAME_TEMPLATES = {
    "title": "%(title)s.%(ext)s",
    "uploader_title": "%(uploader)s - %(title)s.%(ext)s",
    "date_title": "%(upload_date)s - %(title)s.%(ext)s",
}

FORMATS = {
    "best": ["-f", "bv*+ba/b"],
    "1080": ["-f", "bestvideo[height<=1080]+bestaudio/best", "--merge-output-format", "mp4"],
    "720": ["-f", "bestvideo[height<=720]+bestaudio/best", "--merge-output-format", "mp4"],
    "480": ["-f", "bestvideo[height<=480]+bestaudio/best", "--merge-output-format", "mp4"],
    "audio": ["-f", "bestaudio/best", "--extract-audio", "--audio-format", "mp3", "--audio-quality", "192k"],
}

DIRECT_EXTS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v",
    ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".dmg", ".pkg", ".exe", ".msi", ".apk", ".ipa",
    ".iso", ".img", ".bin", ".csv", ".json", ".xml", ".txt", ".epub",
}

YOUTUBE_HOSTS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
)


def ensure_path() -> None:
    os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")


def resolve_tool(name: str) -> str | None:
    ensure_path()
    found = shutil.which(name)
    if found:
        return found
    order = (
        [f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"]
        if platform.machine() == "arm64"
        else [f"/usr/local/bin/{name}", f"/opt/homebrew/bin/{name}"]
    )
    for path in order:
        if Path(path).is_file() and os.access(path, os.X_OK):
            return path
    return None


def hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_youtube(url: str) -> bool:
    host = hostname(url)
    return host in YOUTUBE_HOSTS or host.endswith(".youtube.com")


def path_looks_direct(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    return any(path.endswith(ext) for ext in DIRECT_EXTS)


def _head_headers(url: str, timeout: int = 12) -> dict[str, str] | None:
    req = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": _ua()}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {k.lower(): v for k, v in resp.headers.items()}
    except Exception:
        return None


def looks_like_direct_response(headers: dict[str, str] | None) -> bool:
    if not headers:
        return False
    cd = headers.get("content-disposition", "")
    if "attachment" in cd.lower() or filename_from_cd(cd):
        return True
    ct = headers.get("content-type", "").split(";")[0].strip().lower()
    if not ct or "html" in ct or ct.startswith("text/"):
        return False
    return ct.startswith(("image/", "video/", "audio/", "application/", "font/"))


def use_ytdlp(url: str) -> bool:
    """YouTube / stream pages use yt-dlp; clear file URLs use direct HTTP."""
    if is_youtube(url):
        return True
    if path_looks_direct(url):
        return False
    if looks_like_direct_response(_head_headers(url)):
        return False
    # Other pages (Vimeo, etc.) — let yt-dlp try
    return True


def filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name or "download"
    return name if "." in name else f"{name}.bin"


def filename_from_cd(header: str | None) -> str | None:
    if not header:
        return None
    m = re.search(r"filename\*=UTF-8''([^;]+)", header, re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename="?([^";]+)"?', header, re.I)
    if m:
        return m.group(1).strip()
    return None


def format_size(n: int | None) -> str | None:
    if n is None or n < 0:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.0f} {u}" if u == "B" else f"{size:.1f} {u}"
        size /= 1024
    return None


def format_speed(bps: float | None) -> str | None:
    if bps is None or bps <= 0:
        return None
    label = format_size(int(bps))
    return f"{label}/s" if label else None


def parse_speed_bps(line: str) -> float | None:
    """Parse yt-dlp 'at 1.23MiB/s' into bytes/sec."""
    m = SPEED_RE.search(line or "")
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "B").lower()
    mult = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }.get(unit)
    if mult is None:
        return None
    return value * mult


def parse_eta_seconds(line: str) -> float | None:
    m = ETA_RE.search(line or "")
    if not m:
        return None
    try:
        a, b, c = m.group(1), m.group(2), m.group(3)
        if c is not None:
            return int(a) * 3600 + int(b) * 60 + int(c)
        return int(a) * 60 + int(b)
    except (TypeError, ValueError):
        return None


def format_eta(seconds: float | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    s = int(round(seconds))
    if s < 1:
        return "~0s"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"~{h}h {m}m"
    if m:
        return f"~{m}m {sec}s" if sec else f"~{m}m"
    return f"~{sec}s"


def resolve_outtmpl(key: str | None) -> str:
    if not key:
        return FILENAME_TEMPLATES["title"]
    if key in FILENAME_TEMPLATES:
        return FILENAME_TEMPLATES[key]
    # Allow a short custom template if it looks like yt-dlp
    raw = str(key).strip()
    if "%(" in raw and ")" in raw and ".." not in raw and "/" not in raw:
        if not raw.endswith(".%(ext)s") and "%(ext)s" not in raw:
            raw = f"{raw}.%(ext)s"
        return raw
    return FILENAME_TEMPLATES["title"]


def load_history() -> list[dict]:
    try:
        if HISTORY_PATH.is_file():
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[:HISTORY_MAX]
    except Exception:
        pass
    return []


def save_history(items: list[dict]) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(
            json.dumps(items[:HISTORY_MAX], indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def history_add(entry: dict) -> None:
    items = load_history()
    url = str(entry.get("url") or "")
    path = str(entry.get("path") or "")
    items = [
        i
        for i in items
        if not (
            (url and i.get("url") == url)
            or (path and i.get("path") == path)
        )
    ]
    items.insert(
        0,
        {
            "id": entry.get("id") or str(int(time.time() * 1000)),
            "title": entry.get("title") or url or path,
            "url": url,
            "path": path,
            "outdir": entry.get("outdir") or "",
            "ts": entry.get("ts") or int(time.time()),
        },
    )
    save_history(items)


def notify_macos(title: str, body: str) -> None:
    if platform.system() != "Darwin":
        return
    safe_title = (title or "YTDownloader").replace("\\", "\\\\").replace('"', '\\"')
    safe_body = (body or "").replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{safe_body}" with title "{safe_title}"',
            ],
            check=False,
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass


def reveal_in_finder(path: str) -> bool:
    p = Path(str(path or "")).expanduser()
    if not p.exists():
        return False
    try:
        if p.is_dir():
            subprocess.run(["open", str(p)], check=False)
        else:
            subprocess.run(["open", "-R", str(p)], check=False)
        return True
    except Exception:
        return False


class AppState:
    def __init__(self) -> None:
        self.listeners: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.procs: dict[str, subprocess.Popen[str]] = {}
        self.busy = False
        self.cancel = False
        self.paused = False
        self._http_resps: dict[str, object] = {}
        self.item_pct: dict[str, float] = {}
        self.item_speed: dict[str, float] = {}
        self.item_eta: dict[str, float] = {}

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            self.listeners.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def emit(self, payload: dict) -> None:
        data = json.dumps(payload)
        with self.lock:
            dead = []
            for q in self.listeners:
                try:
                    q.put_nowait(data)
                except Exception:
                    dead.append(q)
            for q in dead:
                self.listeners.remove(q)

    def register_proc(self, job_id: str, proc: subprocess.Popen[str]) -> None:
        with self.lock:
            self.procs[job_id] = proc

    def unregister_proc(self, job_id: str) -> None:
        with self.lock:
            self.procs.pop(job_id, None)

    def register_http(self, job_id: str, resp: object) -> None:
        with self.lock:
            self._http_resps[job_id] = resp

    def unregister_http(self, job_id: str) -> None:
        with self.lock:
            self._http_resps.pop(job_id, None)

    def set_item_pct(self, job_id: str, value: float) -> None:
        with self.lock:
            self.item_pct[job_id] = value

    def set_item_speed(self, job_id: str, bps: float | None) -> None:
        with self.lock:
            if bps is None or bps <= 0:
                self.item_speed.pop(job_id, None)
            else:
                self.item_speed[job_id] = float(bps)

    def clear_item_speed(self, job_id: str) -> None:
        with self.lock:
            self.item_speed.pop(job_id, None)
            self.item_eta.pop(job_id, None)

    def set_item_eta(self, job_id: str, seconds: float | None) -> None:
        with self.lock:
            if seconds is None or seconds < 0:
                self.item_eta.pop(job_id, None)
            else:
                self.item_eta[job_id] = float(seconds)

    def overall_pct(self) -> float:
        with self.lock:
            if not self.item_pct:
                return 0.0
            return sum(self.item_pct.values()) / len(self.item_pct)

    def overall_speed(self) -> float:
        with self.lock:
            return float(sum(self.item_speed.values()))

    def overall_eta(self) -> float | None:
        with self.lock:
            if not self.item_eta:
                return None
            return float(max(self.item_eta.values()))

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        # Freeze / unfreeze active yt-dlp processes (Unix)
        if platform.system() == "Windows":
            return
        with self.lock:
            procs = list(self.procs.values())
        sig = signal.SIGSTOP if self.paused else signal.SIGCONT
        for proc in procs:
            try:
                if proc.poll() is None and proc.pid:
                    os.kill(proc.pid, sig)
            except Exception:
                pass

    def request_cancel(self) -> None:
        self.cancel = True
        was_paused = self.paused
        self.paused = False
        with self.lock:
            procs = list(self.procs.values())
            resps = list(self._http_resps.values())
        for proc in procs:
            try:
                if proc.poll() is None and proc.pid:
                    # Resume first if stopped, then terminate
                    if was_paused and platform.system() != "Windows":
                        try:
                            os.kill(proc.pid, signal.SIGCONT)
                        except Exception:
                            pass
                    proc.terminate()
            except Exception:
                pass
        for resp in resps:
            try:
                resp.close()  # type: ignore[attr-defined]
            except Exception:
                pass


STATE = AppState()


def app_version() -> str:
    for candidate in (
        ROOT / "VERSION",
        ROOT.parent / "Resources" / "VERSION",
        Path(__file__).resolve().parent / "VERSION",
    ):
        try:
            if candidate.is_file():
                raw = candidate.read_text(encoding="utf-8").strip()
                if raw:
                    return raw.lstrip("v")
        except Exception:
            pass
    return APP_VERSION_FALLBACK


def _ua() -> str:
    return f"YTDownloader/{app_version()}"


def parse_version_tuple(raw: str) -> tuple[int, ...]:
    s = str(raw or "").strip().lstrip("v")
    parts: list[int] = []
    for bit in re.split(r"[^\d]+", s):
        if not bit:
            continue
        try:
            parts.append(int(bit))
        except ValueError:
            break
        if len(parts) >= 4:
            break
    return tuple(parts or [0])


def version_newer(remote: str, local: str) -> bool:
    return parse_version_tuple(remote) > parse_version_tuple(local)


def clear_quarantine(path: Path | str) -> None:
    """Remove macOS Gatekeeper quarantine so the app opens without Settings trips."""
    p = Path(path).expanduser()
    if not p.exists():
        return
    try:
        subprocess.run(
            ["xattr", "-cr", str(p)],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass


def adhoc_codesign(path: Path | str) -> None:
    """Ad-hoc sign (no paid Apple account). Helps Gatekeeper accept local apps."""
    if platform.system() != "Darwin":
        return
    p = Path(path).expanduser()
    if not p.exists():
        return
    try:
        subprocess.run(
            ["codesign", "--force", "--deep", "--sign", "-", str(p)],
            check=False,
            capture_output=True,
            timeout=60,
        )
    except Exception:
        pass


def prepare_app_for_open(path: Path | str) -> None:
    clear_quarantine(path)
    adhoc_codesign(path)
    clear_quarantine(path)


def schedule_app_relaunch(app_path: Path | str) -> None:
    """
    Spawn an external relaunch helper, then hard-exit this process.
    AppleScript 'quit' fails when the process shows as Python, so we kill by PID/port/path.
    """
    app = Path(app_path).expanduser()
    cache = Path.home() / "Library" / "Caches" / "YTDownloader"
    cache.mkdir(parents=True, exist_ok=True)
    script = cache / "relaunch.sh"
    old_pid = os.getpid()
    port = ACTIVE_PORT
    # Written to disk so it survives after this process dies
    script.write_text(
        f"""#!/bin/bash
set +e
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:$PATH"
APP={json.dumps(str(app))}
OLD_PID={old_pid}
PORT={port}

# Let the HTTP response flush to the UI
sleep 1.0

# 1) Kill the exact process that started this update
kill -TERM "$OLD_PID" 2>/dev/null || true
sleep 0.35
kill -9 "$OLD_PID" 2>/dev/null || true

# 2) Kill anything still listening on our ports (old + new race)
for p in $(seq {PORT} {PORT + 19}); do
  lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
done
lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true

# 3) Kill by bundle id (works even when process name is Python)
osascript <<'APPLESCRIPT' >/dev/null 2>&1 || true
tell application "System Events"
  try
    set ids to unix id of every process whose bundle identifier is "com.shahzaibzah00r.ytdownloader"
    repeat with pid in ids
      do shell script "kill -9 " & pid
    end repeat
  end try
  try
    set ids to unix id of every process whose name contains "YTDownloader"
    repeat with pid in ids
      do shell script "kill -9 " & pid
    end repeat
  end try
end tell
APPLESCRIPT

# 4) Path-based leftovers (launcher + embedded python)
pkill -9 -f "YTDownloader.app/Contents/MacOS/YTDownloader" 2>/dev/null || true
pkill -9 -f "YTDownloader.app/Contents/Resources/yt_downloader.py" 2>/dev/null || true
pkill -9 -f "/Applications/YTDownloader.app" 2>/dev/null || true

sleep 0.6

# Strip quarantine again (updates can re-flag) then open ONE instance
xattr -cr "$APP" 2>/dev/null || true
xattr -d com.apple.quarantine "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP" 2>/dev/null || true
xattr -cr "$APP" 2>/dev/null || true

# Never use open -n (that forces a second window)
open "$APP"
"""
    )
    os.chmod(script, 0o755)
    subprocess.Popen(
        ["/bin/bash", str(script)],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    def _exit_soon() -> None:
        time.sleep(1.4)
        os._exit(0)

    threading.Thread(target=_exit_soon, daemon=True).start()


def detect_app_bundle() -> Path | None:
    """Locate YTDownloader.app if we're running from an installed bundle."""
    here = Path(__file__).resolve()
    # .../YTDownloader.app/Contents/Resources/yt_downloader.py
    for parent in here.parents:
        if parent.name.endswith(".app"):
            return parent
    for candidate in (
        Path("/Applications/YTDownloader.app"),
        Path.home() / "Applications" / "YTDownloader.app",
    ):
        if candidate.is_dir():
            return candidate
    return None


def arch_dmg_label() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "AppleSilicon"
    return "Intel"


def fetch_latest_release() -> dict:
    req = urllib.request.Request(
        f"{GITHUB_API}/releases/latest",
        headers={
            "User-Agent": f"YTDownloader/{app_version()}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pick_release_asset(release: dict) -> dict | None:
    label = arch_dmg_label()
    assets = release.get("assets") or []
    # Prefer arch-specific DMG
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.endswith(".dmg") and label in name:
            return asset
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.endswith(".dmg"):
            return asset
    return None


def check_app_update() -> dict:
    local = app_version()
    try:
        release = fetch_latest_release()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "current": local,
            "update_available": False,
        }
    tag = str(release.get("tag_name") or "").lstrip("v")
    asset = pick_release_asset(release)
    newer = version_newer(tag, local) if tag else False
    return {
        "ok": True,
        "current": local,
        "latest": tag,
        "update_available": newer,
        "release_url": release.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest",
        "asset_name": (asset or {}).get("name"),
        "asset_url": (asset or {}).get("browser_download_url"),
        "arch": arch_dmg_label(),
        "body": (release.get("body") or "")[:2000],
    }


def _mount_dmg(dmg: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-readonly", str(dmg)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    mount: Path | None = None
    for line in (proc.stdout or "").splitlines():
        if "/Volumes/" in line:
            mount = Path(line[line.index("/Volumes/") :].strip())
    return mount


def _detach_dmg(mount: Path | None) -> None:
    if not mount:
        return
    try:
        subprocess.run(
            ["hdiutil", "detach", str(mount), "-quiet"],
            check=False,
            capture_output=True,
            timeout=60,
        )
    except Exception:
        pass


def _install_bundle(src_app: Path, dest_app: Path) -> tuple[bool, str]:
    """Copy .app to dest, strip quarantine, ad-hoc codesign."""
    dest_app = dest_app.expanduser()
    dest_app.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
set -e
SRC={json.dumps(str(src_app))}
DEST={json.dumps(str(dest_app))}
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
# Clear quarantine on source first so ditto does not copy the flag
xattr -cr "$SRC" 2>/dev/null || true
xattr -d com.apple.quarantine "$SRC" 2>/dev/null || true
ditto "$SRC" "$DEST"
xattr -cr "$DEST" 2>/dev/null || true
xattr -d com.apple.quarantine "$DEST" 2>/dev/null || true
codesign --force --deep --sign - "$DEST" 2>/dev/null || true
xattr -cr "$DEST" 2>/dev/null || true
"""
    # /Applications usually needs an admin password once
    if str(dest_app).startswith("/Applications"):
        asa = "do shell script " + json.dumps(script) + " with administrator privileges"
        proc = subprocess.run(
            ["osascript", "-e", asa],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode == 0:
            return True, str(dest_app)
        # Fall back to ~/Applications (no admin)
        alt = Path.home() / "Applications" / "YTDownloader.app"
        ok, _ = _install_bundle(src_app, alt)
        if ok:
            return True, str(alt)
        err = (proc.stderr or proc.stdout or "Install failed").strip()
        return False, err[-400:]

    proc = subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "Install failed").strip()
        return False, err[-400:]
    return True, str(dest_app)


def install_app_update(asset_url: str, asset_name: str | None = None) -> dict:
    """Download DMG, replace app, clear quarantine + ad-hoc sign (no Apple paid cert)."""
    if platform.system() != "Darwin":
        return {"ok": False, "error": "Updates are only supported on macOS"}
    if not asset_url:
        return {"ok": False, "error": "Missing download URL"}

    dest_app = Path("/Applications/YTDownloader.app")
    current = detect_app_bundle()
    if current and current.name.endswith(".app"):
        dest_app = current

    tmp = Path.home() / "Library" / "Caches" / "YTDownloader" / "updates"
    tmp.mkdir(parents=True, exist_ok=True)
    dmg_name = asset_name or "YTDownloader-update.dmg"
    dmg_path = tmp / Path(dmg_name).name

    STATE.emit({"type": "status", "text": "Downloading update…"})
    STATE.emit({"type": "log", "line": f"Downloading {dmg_name}…", "cls": "muted"})
    try:
        req = urllib.request.Request(
            asset_url,
            headers={"User-Agent": f"YTDownloader/{app_version()}"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp, open(dmg_path, "wb") as fh:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Download failed: {exc}"}

    clear_quarantine(dmg_path)

    STATE.emit({"type": "status", "text": "Installing update…"})
    mount = _mount_dmg(dmg_path)
    if not mount or not mount.exists():
        return {"ok": False, "error": "Could not open the update DMG"}

    try:
        src_app = next((c for c in mount.iterdir() if c.name.endswith(".app")), None)
        if not src_app:
            return {"ok": False, "error": "No .app found in the update DMG"}

        ok, result = _install_bundle(src_app, dest_app)
        if not ok:
            return {"ok": False, "error": result}

        installed = Path(result)
        prepare_app_for_open(installed)
        STATE.emit({"type": "log", "line": f"Updated → {installed}", "cls": "ok"})
        notify_macos("YTDownloader", "Update installed — relaunching…")
        schedule_app_relaunch(installed)
        return {
            "ok": True,
            "path": str(installed),
            "relaunch": True,
            "message": "Update installed. Closing this window and opening the new version…",
        }
    finally:
        _detach_dmg(mount)


def health() -> dict:
    yt = resolve_tool("yt-dlp")
    ff = resolve_tool("ffmpeg")
    missing = [n for n, p in (("yt-dlp", yt), ("ffmpeg", ff)) if not p]
    bundle = detect_app_bundle()
    return {
        "ready": not missing,
        "missing": missing,
        "yt_dlp": yt,
        "ffmpeg": ff,
        "arch": platform.machine(),
        "default_dir": DEFAULT_DIR,
        "version": app_version(),
        "repo": GITHUB_REPO,
        "app_path": str(bundle) if bundle else None,
    }


def format_duration(seconds) -> str | None:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return None
    if s < 0:
        return None
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def best_filesize(info: dict) -> int | None:
    size = info.get("filesize") or info.get("filesize_approx")
    if size:
        try:
            return int(size)
        except (TypeError, ValueError):
            pass
    best = 0
    for fmt in info.get("formats") or []:
        for key in ("filesize", "filesize_approx"):
            val = fmt.get(key)
            if val:
                try:
                    best = max(best, int(val))
                except (TypeError, ValueError):
                    pass
    return best or None


def entry_thumbnail(entry: dict) -> str | None:
    """Prefer tiny YouTube default thumb (fast to load)."""
    vid = entry.get("id")
    if not vid or len(str(vid)) != 11:
        raw = entry.get("url")
        if raw and "://" not in str(raw) and len(str(raw)) == 11:
            vid = raw
    if vid and len(str(vid)) == 11:
        return f"https://i.ytimg.com/vi/{vid}/default.jpg"
    thumbs = entry.get("thumbnails") or []
    if thumbs:
        # First entries are usually the smallest
        return thumbs[0].get("url") or (thumbs[-1].get("url") if thumbs else None)
    if entry.get("thumbnail"):
        return entry["thumbnail"]
    return None


def youtube_video_id(url: str) -> str | None:
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if host in ("youtu.be", "www.youtu.be"):
            vid = u.path.strip("/").split("/")[0]
            return vid if len(vid) == 11 else None
        from urllib.parse import parse_qs

        qs = parse_qs(u.query)
        vid = (qs.get("v") or [None])[0]
        return vid if vid and len(vid) == 11 else None
    except Exception:
        return None


def is_playlist_url(url: str) -> bool:
    low = url.lower()
    return "/playlist" in low or "list=" in low


def preview_youtube_oembed(url: str) -> dict | None:
    """Fast title/thumb via YouTube oEmbed — no yt-dlp, no format probing."""
    from urllib.parse import quote

    vid = youtube_video_id(url)
    if not vid or is_playlist_url(url):
        return None
    api = f"https://www.youtube.com/oembed?format=json&url={quote(url, safe='')}"
    req = urllib.request.Request(api, headers={"User-Agent": _ua()})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    title = data.get("title") or filename_from_url(url)
    watch = f"https://www.youtube.com/watch?v={vid}"
    return {
        "title": title,
        "url": watch,
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/default.jpg",
        "uploader": data.get("author_name"),
        "kind": "YouTube / stream",
        "ext": None,
        "filesize": None,
        "duration": None,
        "is_playlist": False,
        "count": 1,
        "entries": [],
        "id": vid,
    }


def probe_media_meta(url: str) -> dict:
    """Light yt-dlp probe for filesize + duration (single video only)."""
    yt = resolve_tool("yt-dlp")
    if not yt:
        return {}
    cmd = [
        yt,
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--socket-timeout",
        "15",
        "--extractor-args",
        "youtube:player_client=android",
        "-f",
        "bv*+ba/b/best",
        "--print",
        "%(filesize,filesize_approx)s",
        "--print",
        "%(duration)s",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    out: dict = {}
    if lines:
        raw_size = lines[0]
        if raw_size.isdigit():
            out["filesize"] = int(raw_size)
    if len(lines) > 1:
        try:
            out["duration"] = float(lines[1])
        except ValueError:
            pass
    return out


def enrich_preview_meta(data: dict, url: str) -> dict:
    """Fill missing filesize/duration without a full JSON dump when possible."""
    if data.get("is_playlist"):
        return data
    need_size = not data.get("filesize")
    need_dur = not data.get("duration")
    if not need_size and not need_dur:
        return data
    meta = probe_media_meta(url or str(data.get("url") or ""))
    if need_size and meta.get("filesize"):
        data["filesize"] = format_size(int(meta["filesize"]))
    if need_dur and meta.get("duration") is not None:
        data["duration"] = format_duration(meta["duration"])
    return data


def entry_watch_url(entry: dict) -> str | None:
    for key in ("webpage_url", "original_url"):
        val = entry.get(key)
        if val and str(val).startswith("http"):
            return str(val)
    raw = entry.get("url")
    if raw and str(raw).startswith("http"):
        return str(raw)
    vid = entry.get("id")
    if not vid and raw and "://" not in str(raw):
        vid = raw
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    return None


def pick_folder(start: str | None = None) -> str | None:
    """Native macOS folder chooser via AppleScript."""
    initial = str(Path(start or DEFAULT_DIR).expanduser())
    Path(initial).mkdir(parents=True, exist_ok=True)
    # Escape for AppleScript string
    safe = initial.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
try
  set defaultLoc to POSIX file "{safe}"
  set theFolder to choose folder with prompt "Choose save folder" default location defaultLoc
  return POSIX path of theFolder
on error
  return ""
end try
'''
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception:
        return None
    path = (proc.stdout or "").strip()
    return path or None


def read_clipboard() -> str:
    """Read system clipboard (WKWebView blocks navigator.clipboard)."""
    try:
        if platform.system() == "Darwin":
            proc = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return (proc.stdout or "").strip()
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except Exception:
        pass
    return ""


def preview_direct(url: str) -> dict:
    headers = _head_headers(url, timeout=20) or {}
    size = headers.get("content-length")
    name = filename_from_cd(headers.get("content-disposition")) or filename_from_url(url)
    ctype = headers.get("content-type", "").split(";")[0].strip()
    ext = Path(name).suffix.lstrip(".") or None
    size_txt = format_size(int(size)) if size and str(size).isdigit() else None
    return {
        "title": name,
        "url": url,
        "thumbnail": None,
        "uploader": None,
        "kind": "Direct file",
        "ext": ext,
        "filesize": size_txt or (ctype or None),
        "duration": None,
        "is_playlist": False,
        "count": 1,
        "entries": [],
    }


def preview_ytdlp(url: str) -> dict:
    yt = resolve_tool("yt-dlp")
    if not yt:
        raise RuntimeError("yt-dlp is missing — click Fix tools")

    # Flat + skip-download: playlist listings without probing every format (much faster)
    cmd = [
        yt,
        "-J",
        "--flat-playlist",
        "--yes-playlist",
        "--skip-download",
        "--no-warnings",
        "--socket-timeout",
        "20",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "Preview failed").strip().splitlines()
        raise RuntimeError(err[-1] if err else "Preview failed")
    info = json.loads(proc.stdout)

    entries_raw = [e for e in (info.get("entries") or []) if e]
    is_playlist = info.get("_type") == "playlist" or len(entries_raw) > 1

    if is_playlist and entries_raw:
        items = []
        for i, entry in enumerate(entries_raw, start=1):
            watch = entry_watch_url(entry)
            if not watch:
                continue
            items.append({
                "index": i,
                "id": entry.get("id"),
                "title": entry.get("title") or f"Video {i}",
                "url": watch,
                "thumbnail": entry_thumbnail(entry),
                "duration": format_duration(entry.get("duration")),
                "uploader": entry.get("uploader") or entry.get("channel") or info.get("uploader"),
                "filesize": None,  # skip size probe on preview for speed
            })
        thumb = entry_thumbnail(info) or (items[0]["thumbnail"] if items else None)
        return {
            "title": info.get("title") or "Playlist",
            "url": url,
            "thumbnail": thumb,
            "uploader": info.get("uploader") or info.get("channel"),
            "kind": "Playlist / course",
            "ext": None,
            "filesize": None,
            "total_filesize": None,
            "duration": None,
            "is_playlist": True,
            "count": len(items),
            "entries": items,
        }

    if info.get("_type") == "playlist" and not entries_raw:
        raise RuntimeError("Playlist is empty or unavailable")

    # Single video: use flat JSON as-is (no second expensive format fetch)
    vid = info.get("id") or youtube_video_id(url)
    thumb = entry_thumbnail(info) or (
        f"https://i.ytimg.com/vi/{vid}/default.jpg" if vid else None
    )
    watch = info.get("webpage_url") or entry_watch_url(info) or url
    return {
        "title": info.get("title") or filename_from_url(url),
        "url": watch,
        "thumbnail": thumb,
        "uploader": info.get("uploader") or info.get("channel"),
        "kind": "YouTube / stream" if is_youtube(url) else "Media page",
        "ext": info.get("ext"),
        "filesize": None,
        "duration": format_duration(info.get("duration")),
        "is_playlist": False,
        "count": 1,
        "entries": [],
        "id": vid,
    }


def fetch_preview(url: str) -> dict:
    url = url.strip()
    if not url:
        raise ValueError("Missing URL")

    # Fast path: single YouTube video via oEmbed + tiny thumb, then light size probe
    if is_youtube(url) and not is_playlist_url(url):
        fast = preview_youtube_oembed(url)
        if fast:
            return enrich_preview_meta(fast, url)

    if path_looks_direct(url):
        return preview_direct(url)

    # Playlists / other sites — flat yt-dlp (no format probing)
    if is_youtube(url) or use_ytdlp(url):
        try:
            data = preview_ytdlp(url)
            if not data.get("is_playlist"):
                return enrich_preview_meta(data, url)
            return data
        except Exception:
            if is_youtube(url):
                raise
            return preview_direct(url)

    return preview_direct(url)


def _entries_from_preview(data: dict, source_index: int = 1) -> list[dict]:
    """Normalize a preview into a flat list of downloadable entries."""
    entries = list(data.get("entries") or [])
    # Playlist name is useful as source; single-video title is not (duplicates row title)
    playlist_name = data.get("title") if data.get("is_playlist") else None
    if entries:
        out = []
        for e in entries:
            item = dict(e)
            if playlist_name and playlist_name != item.get("title"):
                item["source"] = playlist_name
            if not item.get("uploader"):
                item["uploader"] = data.get("uploader")
            out.append(item)
        return out
    url = data.get("url")
    if not url:
        return []
    return [{
        "index": 1,
        "id": data.get("id"),
        "title": data.get("title") or url,
        "url": url,
        "thumbnail": data.get("thumbnail"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader"),
        "filesize": data.get("filesize"),
        "source": f"URL {source_index}" if source_index else None,
    }]


def normalize_url_key(url: str) -> str:
    """Canonical key so duplicate / alternate YouTube forms collapse."""
    s = (url or "").strip()
    if not s:
        return ""
    try:
        u = urlparse(s)
        host = (u.hostname or "").lower().removeprefix("www.")
        path = (u.path or "").rstrip("/") or "/"
        if host in ("youtu.be",):
            vid = path.lstrip("/").split("/")[0]
            return f"yt:{vid}" if vid else s.lower()
        if host == "youtube.com" or host.endswith(".youtube.com"):
            from urllib.parse import parse_qs

            qs = parse_qs(u.query)
            vid = (qs.get("v") or [None])[0]
            if vid:
                return f"yt:{vid}"
            parts = [p for p in path.split("/") if p]
            if parts and parts[0] in ("shorts", "embed") and len(parts) > 1:
                return f"yt:{parts[1]}"
            plist = (qs.get("list") or [None])[0]
            if parts and parts[0] == "playlist" and plist:
                return f"ytpl:{plist}"
            if plist and not vid:
                return f"ytpl:{plist}"
        return f"{host}{path}{('?' + u.query) if u.query else ''}".lower()
    except Exception:
        return s.lower()


def dedupe_urls(urls: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        url = str(raw or "").strip()
        if not url:
            continue
        key = normalize_url_key(url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out


def fetch_preview_batch(urls: list[str]) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cleaned = dedupe_urls([u.strip() for u in urls if str(u).strip()])
    if not cleaned:
        raise ValueError("Missing URL")
    if len(cleaned) == 1:
        return fetch_preview(cleaned[0])

    merged: list[dict] = []
    errors: list[str] = []
    thumb = None
    workers = min(6, len(cleaned))
    results: dict[int, tuple[str, object]] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(fetch_preview, url): (i, url)
            for i, url in enumerate(cleaned, start=1)
        }
        for fut in as_completed(futs):
            i, url = futs[fut]
            try:
                results[i] = ("ok", fut.result())
            except Exception as exc:  # noqa: BLE001
                results[i] = ("err", f"{url}: {exc}")

    for i in sorted(results):
        kind, payload = results[i]
        if kind == "err":
            errors.append(str(payload))
            continue
        data = payload  # type: ignore[assignment]
        assert isinstance(data, dict)
        if not thumb and data.get("thumbnail"):
            thumb = data["thumbnail"]
        for entry in _entries_from_preview(data, source_index=i):
            merged.append(entry)

    if not merged and errors:
        raise RuntimeError(errors[0])
    if not merged:
        raise RuntimeError("No previews found for batch URLs")

    for i, entry in enumerate(merged, start=1):
        entry["index"] = i
        if not entry.get("id"):
            entry["id"] = f"batch-{i}"

    result = {
        "title": merged[0].get("title") if len(merged) == 1 else f"{len(merged)} videos ready",
        "url": cleaned[0],
        "thumbnail": thumb or merged[0].get("thumbnail"),
        "uploader": None,
        "kind": "Batch preview",
        "ext": None,
        "filesize": None,
        "duration": None,
        "is_playlist": True,
        "count": len(merged),
        "entries": merged,
        "batch_sources": len(cleaned),
    }
    if errors:
        result["warnings"] = errors
    return result


def emit_item(
    job_id: str,
    title: str,
    value: float,
    state: str = "running",
    speed: float | None = None,
    eta: float | None = None,
) -> None:
    pct = max(0.0, min(100.0, float(value)))
    STATE.set_item_pct(job_id, pct if state == "running" else (100.0 if state == "done" else pct))
    if state in ("done", "error"):
        STATE.clear_item_speed(job_id)
        speed = None
        eta = None
    else:
        if speed is not None:
            STATE.set_item_speed(job_id, speed)
        if eta is not None:
            STATE.set_item_eta(job_id, eta)
    speed_bps = STATE.overall_speed() if state == "running" else 0.0
    item_bps = speed
    item_eta = eta
    if state == "running":
        with STATE.lock:
            if item_bps is None:
                item_bps = STATE.item_speed.get(job_id)
            if item_eta is None:
                item_eta = STATE.item_eta.get(job_id)
    overall_eta = STATE.overall_eta() if state == "running" else None
    STATE.emit({
        "type": "item",
        "id": job_id,
        "title": title,
        "value": round(pct, 1),
        "state": state,
        "speed": format_speed(item_bps),
        "speed_bps": round(item_bps, 1) if item_bps else 0,
        "eta": format_eta(item_eta),
        "eta_seconds": round(item_eta, 1) if item_eta is not None else None,
    })
    overall = STATE.overall_pct()
    speed_label = format_speed(speed_bps) if speed_bps > 0 else None
    eta_label = format_eta(overall_eta)
    combo = None
    if speed_label and eta_label:
        combo = f"{speed_label} · {eta_label} left"
    elif speed_label:
        combo = speed_label
    elif eta_label:
        combo = f"{eta_label} left"
    STATE.emit({
        "type": "progress",
        "value": round(overall, 1),
        "speed": combo,
        "speed_bps": round(speed_bps, 1) if speed_bps > 0 else 0,
        "eta": eta_label,
        "eta_seconds": round(overall_eta, 1) if overall_eta is not None else None,
    })


def download_direct(url: str, outdir: Path, job_id: str = "job", title: str | None = None) -> tuple[bool, str | None]:
    label = title or filename_from_url(url)
    outdir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _ua()})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        STATE.emit({"type": "log", "line": f"[{label}] HTTP {exc.code}: {exc.reason}", "cls": "err"})
        emit_item(job_id, label, 0, "error")
        return False, None
    except Exception as exc:  # noqa: BLE001
        STATE.emit({"type": "log", "line": f"[{label}] {exc}", "cls": "err"})
        emit_item(job_id, label, 0, "error")
        return False, None

    STATE.register_http(job_id, resp)
    try:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        name = filename_from_cd(headers.get("content-disposition")) or filename_from_url(url)
        name = Path(name).name or "download.bin"
        dest = outdir / name
        total = headers.get("content-length")
        total_n = int(total) if total and total.isdigit() else None
        STATE.emit({"type": "log", "line": f"[{label}] Saving → {dest}", "cls": "muted"})
        emit_item(job_id, label, 0, "running")
        written = 0
        started = time.monotonic()
        last_emit = 0.0
        with open(dest, "wb") as fh:
            while True:
                while STATE.paused and not STATE.cancel:
                    time.sleep(0.2)
                if STATE.cancel:
                    STATE.emit({"type": "log", "line": f"[{label}] Cancelled.", "cls": "muted"})
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    emit_item(job_id, label, written * 100.0 / total_n if total_n else 0, "error")
                    return False, None
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
                now = time.monotonic()
                elapsed = max(now - started, 0.001)
                bps = written / elapsed
                eta = ((total_n - written) / bps) if total_n and bps > 0 else None
                if total_n:
                    if now - last_emit >= 0.25 or written >= total_n:
                        last_emit = now
                        emit_item(
                            job_id,
                            label,
                            written * 100.0 / total_n,
                            "running",
                            speed=bps,
                            eta=eta,
                        )
                elif now - last_emit >= 0.5:
                    last_emit = now
                    emit_item(job_id, label, 0, "running", speed=bps)
        emit_item(job_id, label, 100, "done")
        STATE.emit({"type": "log", "line": f"[{label}] Saved {name}", "cls": "ok"})
        return True, str(dest)
    finally:
        try:
            resp.close()
        except Exception:
            pass
        STATE.unregister_http(job_id)


def download_ytdlp(
    url: str,
    quality: str,
    outdir: Path,
    label: str | None = None,
    job_id: str = "job",
    title: str | None = None,
    outtmpl: str | None = None,
    write_subs: bool = False,
) -> tuple[bool, str | None]:
    h = health()
    display = title or label or url
    if not h["ready"]:
        STATE.emit({"type": "log", "line": f"Missing tools: {', '.join(h['missing'])}", "cls": "err"})
        emit_item(job_id, display, 0, "error")
        return False, None

    q = quality if quality in FORMATS else "best"
    fmt = FORMATS[q]
    tmpl = resolve_outtmpl(outtmpl)
    cmd = [
        h["yt_dlp"],
        "--newline",
        "--no-colors",
        "--progress",
        "--no-playlist",
        "--ffmpeg-location",
        str(Path(h["ffmpeg"]).parent),
        "-o",
        str(outdir / tmpl),
        *fmt,
    ]
    if write_subs and q != "audio":
        cmd.extend([
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,en",
            "--convert-subs",
            "srt",
        ])
    cmd.append(url)
    tag = label or f"quality={q}"
    STATE.emit({"type": "log", "line": f"[{display}] yt-dlp · {tag}", "cls": "muted"})
    emit_item(job_id, display, 0, "running")
    proc: subprocess.Popen[str] | None = None
    saved_path: str | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        STATE.register_proc(job_id, proc)
        assert proc.stdout is not None
        for line in proc.stdout:
            if STATE.cancel:
                break
            line = line.rstrip()
            STATE.emit({"type": "log", "line": f"[{display}] {line}"})
            dm = DEST_RE.search(line)
            if dm:
                saved_path = dm.group(1).strip().strip('"')
            m = PROGRESS_RE.search(line)
            if m:
                bps = parse_speed_bps(line)
                eta = parse_eta_seconds(line)
                emit_item(
                    job_id,
                    display,
                    float(m.group(1)),
                    "running",
                    speed=bps,
                    eta=eta,
                )
        code = proc.wait()
        if STATE.cancel:
            STATE.emit({"type": "log", "line": f"[{display}] Cancelled.", "cls": "muted"})
            emit_item(job_id, display, STATE.item_pct.get(job_id, 0), "error")
            return False, None
        if code == 0:
            STATE.emit({"type": "log", "line": f"[{display}] Download finished.", "cls": "ok"})
            emit_item(job_id, display, 100, "done")
            return True, saved_path
        STATE.emit({"type": "log", "line": f"[{display}] Failed (exit {code})", "cls": "err"})
        emit_item(job_id, display, STATE.item_pct.get(job_id, 0), "error")
        return False, None
    except Exception as exc:  # noqa: BLE001
        STATE.emit({"type": "log", "line": f"[{display}] {exc}", "cls": "err"})
        emit_item(job_id, display, 0, "error")
        return False, None
    finally:
        if proc is not None:
            STATE.unregister_proc(job_id)


def download_ytdlp_media(
    url: str,
    quality: str,
    outdir: Path,
    media: str,
    job_id: str = "job",
    title: str | None = None,
    outtmpl: str | None = None,
    write_subs: bool = False,
) -> tuple[bool, str | None]:
    media = (media or "video").lower()
    if media not in ("video", "audio", "both"):
        media = "video"
    display = title or url
    last_path: str | None = None

    if media in ("video", "both"):
        vq = quality if quality in FORMATS and quality != "audio" else "best"
        ok, path = download_ytdlp(
            url,
            vq,
            outdir,
            label=f"video · {vq}",
            job_id=job_id,
            title=display,
            outtmpl=outtmpl,
            write_subs=write_subs,
        )
        if path:
            last_path = path
        if not ok or STATE.cancel:
            return False, last_path

    if media in ("audio", "both"):
        if media == "both":
            emit_item(job_id, f"{display} (audio)", 0, "running")
        ok, path = download_ytdlp(
            url,
            "audio",
            outdir,
            label="audio · mp3",
            job_id=job_id,
            title=f"{display} (MP3)" if media == "both" else display,
            outtmpl=outtmpl,
            write_subs=False,
        )
        if path:
            last_path = path
        if not ok or STATE.cancel:
            return False, last_path

    return True, last_path


def download_one(
    job: dict,
    quality: str,
    outdir: Path,
    media: str,
    outtmpl: str | None = None,
    write_subs: bool = False,
) -> tuple[bool, str | None]:
    url = str(job.get("url") or "").strip()
    title = str(job.get("title") or url)
    job_id = str(job.get("id") or url)
    if not url:
        return False, None
    if STATE.cancel:
        return False, None

    STATE.emit({"type": "log", "line": f"── {title}", "cls": "ok"})
    STATE.emit({"type": "log", "line": f"Media: {media}", "cls": "muted"})
    emit_item(job_id, title, 0, "running")

    success = False
    path: str | None = None
    if path_looks_direct(url) or (
        not is_youtube(url) and looks_like_direct_response(_head_headers(url))
    ):
        success, path = download_direct(url, outdir, job_id=job_id, title=title)
    elif use_ytdlp(url):
        success, path = download_ytdlp_media(
            url,
            quality,
            outdir,
            media,
            job_id=job_id,
            title=title,
            outtmpl=outtmpl,
            write_subs=write_subs,
        )
        if not success and not is_youtube(url) and not STATE.cancel:
            STATE.emit({"type": "log", "line": f"[{title}] Retrying as direct file…", "cls": "muted"})
            success, path = download_direct(url, outdir, job_id=job_id, title=title)
    else:
        success, path = download_direct(url, outdir, job_id=job_id, title=title)
    return success, path


def run_queue(
    jobs: list[dict],
    quality: str,
    outdir: str,
    media: str = "video",
    concurrency: int = 1,
    outtmpl: str | None = None,
    write_subs: bool = False,
) -> None:
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

    out = Path(outdir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    total = len(jobs)
    concurrency = max(1, min(6, int(concurrency or 1)))
    concurrency = min(concurrency, total) if total else 1
    tmpl = resolve_outtmpl(outtmpl)

    STATE.item_pct = {}
    STATE.item_speed = {}
    STATE.item_eta = {}
    STATE.paused = False
    STATE.emit({"type": "progress", "value": 0, "speed": None, "speed_bps": 0})
    STATE.emit({"type": "paused", "value": False})
    STATE.emit({
        "type": "queue",
        "text": f"0/{total} done · {concurrency} at a time",
    })
    STATE.emit({
        "type": "status",
        "text": f"Downloading {total} item(s) ({concurrency} parallel)…",
    })
    STATE.emit({
        "type": "items_init",
        "items": [
            {
                "id": str(j.get("id") or j.get("url")),
                "title": str(j.get("title") or j.get("url")),
                "url": str(j.get("url") or ""),
            }
            for j in jobs
        ],
    })

    ok = 0
    fail = 0
    finished = 0
    pending = list(jobs)
    active: dict = {}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while (pending or active) and not STATE.cancel:
            while STATE.paused and not STATE.cancel:
                time.sleep(0.25)

            if STATE.cancel:
                break

            while len(active) < concurrency and pending and not STATE.paused and not STATE.cancel:
                job = pending.pop(0)
                fut = pool.submit(
                    download_one,
                    job,
                    quality,
                    out,
                    media,
                    tmpl,
                    write_subs,
                )
                active[fut] = job

            if not active:
                if STATE.paused and pending:
                    time.sleep(0.25)
                    continue
                break

            done, _ = wait(active.keys(), timeout=0.4, return_when=FIRST_COMPLETED)
            if not done:
                continue
            for fut in done:
                job = active.pop(fut)
                title = str(job.get("title") or job.get("url"))
                path = None
                try:
                    success, path = fut.result()
                    success = bool(success)
                except Exception as exc:  # noqa: BLE001
                    success = False
                    STATE.emit({"type": "log", "line": f"[{title}] {exc}", "cls": "err"})
                finished += 1
                if success:
                    ok += 1
                    history_add({
                        "title": title,
                        "url": str(job.get("url") or ""),
                        "path": path or "",
                        "outdir": str(out),
                        "id": str(job.get("id") or ""),
                    })
                    STATE.emit({"type": "history", "items": load_history()})
                else:
                    fail += 1
                STATE.emit({
                    "type": "queue",
                    "text": f"{finished}/{total} done · {concurrency} at a time"
                    + (" · paused" if STATE.paused else ""),
                })
                STATE.emit({
                    "type": "status",
                    "text": f"{finished}/{total} finished ({ok} ok, {fail} failed)"
                    + (" — paused" if STATE.paused else ""),
                })

        if STATE.cancel:
            for fut in list(active):
                fut.cancel()
            for proc in list(STATE.procs.values()):
                try:
                    if proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass

    if STATE.cancel:
        summary = f"Cancelled — {ok} done, {fail} failed"
        STATE.emit({"type": "status", "text": summary})
    elif fail == 0:
        summary = f"All done — {ok} of {total} saved"
        STATE.emit({"type": "status", "text": summary})
        STATE.emit({"type": "progress", "value": 100})
    else:
        summary = f"Finished — {ok} ok, {fail} failed of {total}"
        STATE.emit({"type": "status", "text": summary})

    notify_macos("YTDownloader", summary)
    STATE.emit({"type": "queue", "text": ""})
    STATE.busy = False
    STATE.cancel = False
    STATE.paused = False
    STATE.emit({"type": "paused", "value": False})
    STATE.emit({"type": "done"})


def run_fix_tools() -> None:
    brew = resolve_tool("brew") or shutil.which("brew")
    if not brew:
        STATE.emit({"type": "error", "text": "Homebrew not found. Install from https://brew.sh"})
        STATE.emit({"type": "done"})
        STATE.busy = False
        return
    try:
        proc = subprocess.Popen(
            [brew, "install", "yt-dlp", "ffmpeg"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            STATE.emit({"type": "log", "line": line.rstrip(), "cls": "muted"})
        code = proc.wait()
        if code == 0:
            STATE.emit({"type": "log", "line": "Tools installed.", "cls": "ok"})
            STATE.emit({"type": "status", "text": "Tools ready"})
        else:
            STATE.emit({"type": "error", "text": f"brew failed ({code})"})
    except Exception as exc:  # noqa: BLE001
        STATE.emit({"type": "error", "text": str(exc)})
    finally:
        STATE.busy = False
        STATE.emit({"type": "done"})


def run_update_ytdlp() -> None:
    brew = resolve_tool("brew") or shutil.which("brew")
    yt = resolve_tool("yt-dlp")
    try:
        if brew:
            cmd = [brew, "upgrade", "yt-dlp"]
            STATE.emit({"type": "log", "line": "Updating yt-dlp via Homebrew…", "cls": "muted"})
        elif yt:
            cmd = [yt, "-U"]
            STATE.emit({"type": "log", "line": "Updating yt-dlp…", "cls": "muted"})
        else:
            STATE.emit({"type": "error", "text": "yt-dlp / Homebrew not found"})
            return
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            STATE.emit({"type": "log", "line": line.rstrip(), "cls": "muted"})
        code = proc.wait()
        if code == 0:
            STATE.emit({"type": "log", "line": "yt-dlp updated.", "cls": "ok"})
            STATE.emit({"type": "status", "text": "yt-dlp up to date"})
            notify_macos("YTDownloader", "yt-dlp updated")
        else:
            STATE.emit({"type": "error", "text": f"Update failed ({code})"})
    except Exception as exc:  # noqa: BLE001
        STATE.emit({"type": "error", "text": str(exc)})
    finally:
        STATE.busy = False
        STATE.emit({"type": "done"})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBUI), **kwargs)

    def log_message(self, fmt: str, *args) -> None:  # quieter
        if args and str(args[0]).startswith(("GET /api/events",)):
            return
        super().log_message(fmt, *args)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(200, health())
            return
        if path == "/api/check-update":
            self._json(200, check_app_update())
            return
        if path == "/api/clipboard":
            self._json(200, {"text": read_clipboard()})
            return
        if path == "/api/history":
            self._json(200, {"items": load_history()})
            return
        if path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = STATE.subscribe()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(f"data: {msg}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                STATE.unsubscribe(q)
            return
        if path in ("/", "/index.html"):
            self.path = "/index.html"
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        data = self._read_json()

        if path == "/api/open-folder":
            folder = Path(str(data.get("path") or DEFAULT_DIR)).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(folder)], check=False)
            self._json(200, {"ok": True})
            return

        if path == "/api/reveal":
            target = str(data.get("path") or "")
            if reveal_in_finder(target):
                self._json(200, {"ok": True})
            else:
                # Fall back to folder if file missing
                folder = str(data.get("outdir") or DEFAULT_DIR)
                folder_p = Path(folder).expanduser()
                folder_p.mkdir(parents=True, exist_ok=True)
                subprocess.run(["open", str(folder_p)], check=False)
                self._json(200, {"ok": True, "fallback": True})
            return

        if path == "/api/pick-folder":
            chosen = pick_folder(str(data.get("path") or DEFAULT_DIR))
            if not chosen:
                self._json(200, {"cancelled": True})
                return
            self._json(200, {"path": chosen, "cancelled": False})
            return

        if path == "/api/preview":
            urls = data.get("urls")
            try:
                if isinstance(urls, list) and urls:
                    self._json(200, fetch_preview_batch([str(u) for u in urls]))
                else:
                    url = str(data.get("url") or "").strip()
                    self._json(200, fetch_preview(url))
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"error": str(exc)})
            return

        if path == "/api/cancel":
            STATE.request_cancel()
            STATE.emit({"type": "status", "text": "Cancelling…"})
            self._json(200, {"ok": True})
            return

        if path == "/api/pause":
            if not STATE.busy:
                self._json(409, {"error": "Nothing downloading"})
                return
            STATE.set_paused(True)
            STATE.emit({"type": "paused", "value": True})
            STATE.emit({
                "type": "progress",
                "value": round(STATE.overall_pct(), 1),
                "speed": "Paused",
                "speed_bps": 0,
                "eta": None,
            })
            STATE.emit({"type": "status", "text": "Paused"})
            STATE.emit({"type": "log", "line": "Downloads paused", "cls": "muted"})
            self._json(200, {"ok": True, "paused": True})
            return

        if path == "/api/resume":
            if not STATE.busy:
                self._json(409, {"error": "Nothing downloading"})
                return
            STATE.set_paused(False)
            STATE.emit({"type": "paused", "value": False})
            STATE.emit({"type": "status", "text": "Resumed"})
            STATE.emit({"type": "log", "line": "Downloads resumed", "cls": "ok"})
            self._json(200, {"ok": True, "paused": False})
            return

        if path == "/api/fix-tools":
            if STATE.busy:
                self._json(409, {"error": "Busy"})
                return
            STATE.busy = True
            STATE.cancel = False
            threading.Thread(target=run_fix_tools, daemon=True).start()
            self._json(200, {"ok": True})
            return

        if path == "/api/install-update":
            if STATE.busy:
                self._json(409, {"error": "Busy — finish or cancel downloads first"})
                return
            asset_url = str(data.get("asset_url") or "").strip()
            asset_name = str(data.get("asset_name") or "").strip() or None
            if not asset_url:
                info = check_app_update()
                if not info.get("update_available") or not info.get("asset_url"):
                    self._json(400, {"error": info.get("error") or "No update available"})
                    return
                asset_url = str(info["asset_url"])
                asset_name = str(info.get("asset_name") or "") or None
            STATE.busy = True
            STATE.cancel = False

            def _run() -> None:
                try:
                    result = install_app_update(asset_url, asset_name)
                    if result.get("ok"):
                        STATE.emit({"type": "status", "text": result.get("message") or "Updated"})
                        STATE.emit({"type": "app_update", "result": result})
                    else:
                        STATE.emit({"type": "error", "text": result.get("error") or "Update failed"})
                finally:
                    STATE.busy = False
                    STATE.emit({"type": "done"})

            threading.Thread(target=_run, daemon=True).start()
            self._json(200, {"ok": True, "started": True})
            return

        if path == "/api/update-ytdlp":
            if STATE.busy:
                self._json(409, {"error": "Busy"})
                return
            STATE.busy = True
            STATE.cancel = False
            threading.Thread(target=run_update_ytdlp, daemon=True).start()
            self._json(200, {"ok": True})
            return

        if path == "/api/download":
            if STATE.busy:
                self._json(409, {"error": "Already downloading"})
                return

            jobs_in = data.get("jobs")
            job_list: list[dict] = []
            if isinstance(jobs_in, list) and jobs_in:
                for i, raw in enumerate(jobs_in, start=1):
                    if isinstance(raw, str):
                        url = raw.strip()
                        if not url:
                            continue
                        job_list.append({"url": url, "title": url, "id": f"job-{i}"})
                    elif isinstance(raw, dict):
                        url = str(raw.get("url") or "").strip()
                        if not url:
                            continue
                        title = str(raw.get("title") or url).strip() or url
                        jid = str(raw.get("id") or f"job-{i}")
                        job_list.append({"url": url, "title": title, "id": jid})
            else:
                urls = data.get("urls")
                if isinstance(urls, list):
                    url_list = [str(u).strip() for u in urls if str(u).strip()]
                else:
                    one = str(data.get("url") or "").strip()
                    url_list = [one] if one else []
                job_list = [
                    {"url": u, "title": u, "id": f"job-{i}"}
                    for i, u in enumerate(url_list, start=1)
                ]

            if not job_list:
                self._json(400, {"error": "Missing URL"})
                return

            # Drop duplicate URLs (same watch id / playlist / path)
            deduped_jobs: list[dict] = []
            seen_keys: set[str] = set()
            for job in job_list:
                key = normalize_url_key(str(job.get("url") or ""))
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped_jobs.append(job)
            job_list = deduped_jobs
            if not job_list:
                self._json(400, {"error": "Missing URL"})
                return

            quality = str(data.get("quality") or "best")
            media = str(data.get("media") or "video").lower()
            if media not in ("video", "audio", "both"):
                media = "video"
            outdir = str(data.get("outdir") or DEFAULT_DIR)
            try:
                concurrency = int(data.get("concurrency") or 1)
            except (TypeError, ValueError):
                concurrency = 1
            concurrency = max(1, min(6, concurrency))
            outtmpl = resolve_outtmpl(str(data.get("template") or "title"))
            write_subs = bool(data.get("subs"))

            STATE.busy = True
            STATE.cancel = False
            STATE.paused = False
            threading.Thread(
                target=run_queue,
                args=(job_list, quality, outdir, media, concurrency, outtmpl, write_subs),
                daemon=True,
            ).start()
            self._json(200, {"ok": True, "count": len(job_list), "concurrency": concurrency})
            return

        self._json(404, {"error": "Not found"})


def start_server() -> tuple[ThreadingHTTPServer, str]:
    if not WEBUI.exists():
        raise SystemExit(f"Missing webui folder: {WEBUI}")

    global ACTIVE_PORT
    httpd = None
    last_err = None
    port = PORT
    for p in range(PORT, PORT + 20):
        try:
            httpd = ThreadingHTTPServer((HOST, p), Handler)
            port = p
            break
        except OSError as exc:
            last_err = exc
    if httpd is None:
        raise SystemExit(f"Could not bind port: {last_err}")

    ACTIVE_PORT = port
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://{HOST}:{port}/"


def open_native_window(url: str) -> bool:
    """Open UI in a real macOS app window (not Safari/Chrome)."""
    try:
        import webview  # type: ignore
    except ImportError:
        return False

    # Near full-screen desktop window
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.destroy()
        width = max(1100, int(sw * 0.92))
        height = max(740, int(sh * 0.90))
    except Exception:
        width, height = 1280, 860

    webview.create_window(
        title="YTDownloader",
        url=url,
        width=width,
        height=height,
        min_size=(900, 640),
        maximized=True,
        background_color="#0b0d10",
    )
    webview.start(gui="cocoa")
    return True


def main() -> None:
    ensure_path()
    # Soften Gatekeeper friction for unsigned OSS builds (no paid Apple cert)
    bundle = detect_app_bundle()
    if bundle:
        prepare_app_for_open(bundle)
    httpd, url = start_server()
    print(f"YTDownloader backend: {url} · v{app_version()}")

    try:
        if open_native_window(url):
            return
        import webbrowser

        print("pywebview not installed — opening browser fallback.")
        print("For a real app window:  pip install pywebview")
        print("Or run:  ./setup.sh")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
