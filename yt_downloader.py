#!/usr/bin/env python3
"""YTDownloader — local dark web UI (stdlib only). Opens in your browser."""

from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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


class AppState:
    def __init__(self) -> None:
        self.listeners: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.proc: subprocess.Popen[str] | None = None
        self.busy = False

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


def run_download(url: str, quality: str, outdir: str) -> None:
    h = health()
    if not h["ready"]:
        STATE.emit({"type": "error", "text": f"Missing tools: {', '.join(h['missing'])}"})
        STATE.emit({"type": "done"})
        STATE.busy = False
        return

    out = Path(outdir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    fmt = FORMATS.get(quality, FORMATS["best"])
    cmd = [
        h["yt_dlp"],
        "--newline",
        "--no-colors",
        "--progress",
        "--ffmpeg-location",
        str(Path(h["ffmpeg"]).parent),
        "-o",
        str(out / "%(title)s.%(ext)s"),
        *fmt,
        url,
    ]
    STATE.emit({"type": "log", "line": f"Quality: {quality} → {out}", "cls": "muted"})
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
            line = line.rstrip()
            STATE.emit({"type": "log", "line": line})
            m = PROGRESS_RE.search(line)
            if m:
                STATE.emit({"type": "progress", "value": float(m.group(1))})
        code = STATE.proc.wait()
        if code == 0:
            STATE.emit({"type": "status", "text": "Done — file saved in your folder"})
            STATE.emit({"type": "log", "line": "Download finished.", "cls": "ok"})
            STATE.emit({"type": "progress", "value": 100})
        else:
            STATE.emit({"type": "status", "text": "Download failed — see Activity"})
            STATE.emit({"type": "log", "line": f"Failed (exit {code})", "cls": "err"})
    except Exception as exc:  # noqa: BLE001
        STATE.emit({"type": "error", "text": str(exc)})
    finally:
        STATE.proc = None
        STATE.busy = False
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

        if path == "/api/cancel":
            if STATE.proc and STATE.proc.poll() is None:
                STATE.busy = False
                STATE.proc.terminate()
                STATE.emit({"type": "log", "line": "Cancelled.", "cls": "muted"})
                STATE.emit({"type": "status", "text": "Cancelled"})
            self._json(200, {"ok": True})
            return

        if path == "/api/fix-tools":
            if STATE.busy:
                self._json(409, {"error": "Busy"})
                return
            STATE.busy = True
            threading.Thread(target=run_fix_tools, daemon=True).start()
            self._json(200, {"ok": True})
            return

        if path == "/api/download":
            if STATE.busy:
                self._json(409, {"error": "Already downloading"})
                return
            url = str(data.get("url") or "").strip()
            if not url:
                self._json(400, {"error": "Missing URL"})
                return
            quality = str(data.get("quality") or "best")
            outdir = str(data.get("outdir") or DEFAULT_DIR)
            STATE.busy = True
            threading.Thread(
                target=run_download, args=(url, quality, outdir), daemon=True
            ).start()
            self._json(200, {"ok": True})
            return

        self._json(404, {"error": "Not found"})


def main() -> None:
    ensure_path()
    if not WEBUI.exists():
        raise SystemExit(f"Missing webui folder: {WEBUI}")

    # Find a free port near 8765
    port = PORT
    httpd = None
    last_err = None
    for p in range(PORT, PORT + 20):
        try:
            httpd = ThreadingHTTPServer((HOST, p), Handler)
            port = p
            break
        except OSError as exc:
            last_err = exc
    if httpd is None:
        raise SystemExit(f"Could not bind port: {last_err}")

    url = f"http://{HOST}:{port}/"
    print(f"YTDownloader running at {url}")
    print("Press Ctrl+C to stop.")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
