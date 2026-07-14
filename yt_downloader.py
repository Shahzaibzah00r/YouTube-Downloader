#!/usr/bin/env python3
"""YTDownloader — native desktop app (HTML UI inside a Mac window)."""

from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
WEBUI = ROOT / "webui"
HOST = "127.0.0.1"
PORT = 8765
DEFAULT_DIR = str(Path.home() / "Downloads")
PROGRESS_RE = re.compile(r"\[download\]\s+([0-9.]+)%")

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
        url, method="HEAD", headers={"User-Agent": "YTDownloader/1.6"}
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


class AppState:
    def __init__(self) -> None:
        self.listeners: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.proc: subprocess.Popen[str] | None = None
        self.busy = False
        self.cancel = False
        self._http_resp = None

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

    def request_cancel(self) -> None:
        self.cancel = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        if self._http_resp is not None:
            try:
                self._http_resp.close()
            except Exception:
                pass


STATE = AppState()


def health() -> dict:
    yt = resolve_tool("yt-dlp")
    ff = resolve_tool("ffmpeg")
    missing = [n for n, p in (("yt-dlp", yt), ("ffmpeg", ff)) if not p]
    return {
        "ready": not missing,
        "missing": missing,
        "yt_dlp": yt,
        "ffmpeg": ff,
        "arch": platform.machine(),
        "default_dir": DEFAULT_DIR,
    }


def preview_direct(url: str) -> dict:
    headers = _head_headers(url, timeout=20) or {}
    size = headers.get("content-length")
    name = filename_from_cd(headers.get("content-disposition")) or filename_from_url(url)
    ctype = headers.get("content-type", "").split(";")[0].strip()
    ext = Path(name).suffix.lstrip(".") or None
    size_txt = format_size(int(size)) if size and str(size).isdigit() else None
    return {
        "title": name,
        "thumbnail": None,
        "uploader": None,
        "kind": "Direct file",
        "ext": ext,
        "filesize": size_txt or (ctype or None),
    }


def preview_ytdlp(url: str) -> dict:
    yt = resolve_tool("yt-dlp")
    if not yt:
        raise RuntimeError("yt-dlp is missing — click Fix tools")
    cmd = [yt, "-J", "--no-playlist", "--no-warnings", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "Preview failed").strip().splitlines()
        raise RuntimeError(err[-1] if err else "Preview failed")
    info = json.loads(proc.stdout)
    thumb = None
    if info.get("thumbnail"):
        thumb = info["thumbnail"]
    elif info.get("thumbnails"):
        thumb = info["thumbnails"][-1].get("url")
    filesize = info.get("filesize") or info.get("filesize_approx")
    return {
        "title": info.get("title") or filename_from_url(url),
        "thumbnail": thumb,
        "uploader": info.get("uploader") or info.get("channel"),
        "kind": "YouTube / stream" if is_youtube(url) else "Media page",
        "ext": info.get("ext"),
        "filesize": format_size(filesize) if filesize else None,
    }


def fetch_preview(url: str) -> dict:
    url = url.strip()
    if not url:
        raise ValueError("Missing URL")

    if path_looks_direct(url) or looks_like_direct_response(_head_headers(url)):
        return preview_direct(url)

    if is_youtube(url) or use_ytdlp(url):
        try:
            return preview_ytdlp(url)
        except Exception:
            if is_youtube(url):
                raise
            return preview_direct(url)

    return preview_direct(url)


def download_direct(url: str, outdir: Path) -> bool:
    outdir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "YTDownloader/1.6"})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        STATE.emit({"type": "log", "line": f"HTTP {exc.code}: {exc.reason}", "cls": "err"})
        return False
    except Exception as exc:  # noqa: BLE001
        STATE.emit({"type": "log", "line": str(exc), "cls": "err"})
        return False

    STATE._http_resp = resp
    try:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        name = filename_from_cd(headers.get("content-disposition")) or filename_from_url(url)
        # Avoid path traversal
        name = Path(name).name or "download.bin"
        dest = outdir / name
        total = headers.get("content-length")
        total_n = int(total) if total and total.isdigit() else None
        STATE.emit({"type": "log", "line": f"Saving → {dest}", "cls": "muted"})
        written = 0
        with open(dest, "wb") as fh:
            while True:
                if STATE.cancel:
                    STATE.emit({"type": "log", "line": "Cancelled.", "cls": "muted"})
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return False
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
                if total_n:
                    pct = written * 100.0 / total_n
                    STATE.emit({"type": "progress", "value": pct})
                    STATE.emit({
                        "type": "status",
                        "text": f"Downloading… {format_size(written)} / {format_size(total_n)}",
                    })
                else:
                    STATE.emit({"type": "status", "text": f"Downloading… {format_size(written)}"})
        STATE.emit({"type": "progress", "value": 100})
        STATE.emit({"type": "log", "line": f"Saved {name}", "cls": "ok"})
        return True
    finally:
        try:
            resp.close()
        except Exception:
            pass
        STATE._http_resp = None


def download_ytdlp(url: str, quality: str, outdir: Path, label: str | None = None) -> bool:
    h = health()
    if not h["ready"]:
        STATE.emit({"type": "log", "line": f"Missing tools: {', '.join(h['missing'])}", "cls": "err"})
        return False

    q = quality if quality in FORMATS else "best"
    fmt = FORMATS[q]
    cmd = [
        h["yt_dlp"],
        "--newline",
        "--no-colors",
        "--progress",
        "--ffmpeg-location",
        str(Path(h["ffmpeg"]).parent),
        "-o",
        str(outdir / "%(title)s.%(ext)s"),
        *fmt,
        url,
    ]
    tag = label or f"quality={q}"
    STATE.emit({"type": "log", "line": f"yt-dlp · {tag}", "cls": "muted"})
    try:
        STATE.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        assert STATE.proc.stdout is not None
        for line in STATE.proc.stdout:
            if STATE.cancel:
                break
            line = line.rstrip()
            STATE.emit({"type": "log", "line": line})
            m = PROGRESS_RE.search(line)
            if m:
                STATE.emit({"type": "progress", "value": float(m.group(1))})
        code = STATE.proc.wait()
        if STATE.cancel:
            STATE.emit({"type": "log", "line": "Cancelled.", "cls": "muted"})
            return False
        if code == 0:
            STATE.emit({"type": "log", "line": "Download finished.", "cls": "ok"})
            STATE.emit({"type": "progress", "value": 100})
            return True
        STATE.emit({"type": "log", "line": f"Failed (exit {code})", "cls": "err"})
        return False
    except Exception as exc:  # noqa: BLE001
        STATE.emit({"type": "log", "line": str(exc), "cls": "err"})
        return False
    finally:
        STATE.proc = None


def download_ytdlp_media(url: str, quality: str, outdir: Path, media: str) -> bool:
    media = (media or "video").lower()
    if media not in ("video", "audio", "both"):
        media = "video"

    ok = True
    if media in ("video", "both"):
        vq = quality if quality in FORMATS and quality != "audio" else "best"
        STATE.emit({"type": "status", "text": "Downloading video…"})
        ok = download_ytdlp(url, vq, outdir, label=f"video · {vq}")
        if not ok or STATE.cancel:
            return False

    if media in ("audio", "both"):
        if media == "both":
            STATE.emit({"type": "progress", "value": 0})
            STATE.emit({"type": "status", "text": "Downloading audio (MP3)…"})
        else:
            STATE.emit({"type": "status", "text": "Downloading audio…"})
        ok = download_ytdlp(url, "audio", outdir, label="audio · mp3")
        if not ok or STATE.cancel:
            return False

    return True


def run_queue(urls: list[str], quality: str, outdir: str, media: str = "video") -> None:
    out = Path(outdir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    total = len(urls)
    ok = 0
    fail = 0

    for i, url in enumerate(urls, start=1):
        if STATE.cancel:
            break
        STATE.emit({"type": "progress", "value": 0})
        STATE.emit({
            "type": "queue",
            "text": f"Item {i} of {total}",
        })
        STATE.emit({"type": "status", "text": f"[{i}/{total}] Starting…"})
        STATE.emit({"type": "log", "line": f"── [{i}/{total}] {url}", "cls": "ok"})
        STATE.emit({"type": "log", "line": f"Media: {media}", "cls": "muted"})

        success = False
        if path_looks_direct(url) or (
            not is_youtube(url) and looks_like_direct_response(_head_headers(url))
        ):
            success = download_direct(url, out)
        elif use_ytdlp(url):
            success = download_ytdlp_media(url, quality, out, media)
            if not success and not is_youtube(url) and not STATE.cancel:
                STATE.emit({"type": "log", "line": "Retrying as direct file URL…", "cls": "muted"})
                success = download_direct(url, out)
        else:
            success = download_direct(url, out)

        if STATE.cancel:
            break
        if success:
            ok += 1
        else:
            fail += 1

    if STATE.cancel:
        STATE.emit({"type": "status", "text": f"Cancelled — {ok} done, {fail} failed"})
    elif fail == 0:
        STATE.emit({"type": "status", "text": f"All done — {ok} of {total} saved"})
    else:
        STATE.emit({"type": "status", "text": f"Finished — {ok} ok, {fail} failed of {total}"})

    STATE.emit({"type": "queue", "text": ""})
    STATE.busy = False
    STATE.cancel = False
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

        if path == "/api/preview":
            url = str(data.get("url") or "").strip()
            try:
                self._json(200, fetch_preview(url))
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"error": str(exc)})
            return

        if path == "/api/cancel":
            STATE.request_cancel()
            STATE.emit({"type": "status", "text": "Cancelling…"})
            self._json(200, {"ok": True})
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

        if path == "/api/download":
            if STATE.busy:
                self._json(409, {"error": "Already downloading"})
                return
            urls = data.get("urls")
            if isinstance(urls, list):
                url_list = [str(u).strip() for u in urls if str(u).strip()]
            else:
                one = str(data.get("url") or "").strip()
                url_list = [one] if one else []
            if not url_list:
                self._json(400, {"error": "Missing URL"})
                return
            quality = str(data.get("quality") or "best")
            media = str(data.get("media") or "video").lower()
            if media not in ("video", "audio", "both"):
                media = "video"
            outdir = str(data.get("outdir") or DEFAULT_DIR)
            STATE.busy = True
            STATE.cancel = False
            threading.Thread(
                target=run_queue, args=(url_list, quality, outdir, media), daemon=True
            ).start()
            self._json(200, {"ok": True, "count": len(url_list)})
            return

        self._json(404, {"error": "Not found"})


def start_server() -> tuple[ThreadingHTTPServer, str]:
    if not WEBUI.exists():
        raise SystemExit(f"Missing webui folder: {WEBUI}")

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
    httpd, url = start_server()
    print(f"YTDownloader backend: {url}")

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
