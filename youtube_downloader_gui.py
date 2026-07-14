#!/usr/bin/env python3
"""Shahzaib YouTube Downloader — GUI for Intel and Apple Silicon Macs."""

from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

HOME = Path.home()
DEFAULT_DIR = HOME / "Downloads"
CONFIG_DIR = HOME / "Library" / "Application Support" / "ShahzaibYouTubeDownloader"
CONFIG_FILE = CONFIG_DIR / "settings.json"
PROGRESS_RE = re.compile(r"\[download\]\s+([0-9.]+)%")
APP_NAME = "Shahzaib YouTube Downloader"

QUALITY_OPTIONS = {
    "Best available": ["-f", "bv*+ba/b"],
    "1080p MP4": ["-f", "bestvideo[height<=1080]+bestaudio/best", "--merge-output-format", "mp4"],
    "720p MP4": ["-f", "bestvideo[height<=720]+bestaudio/best", "--merge-output-format", "mp4"],
    "480p MP4": ["-f", "bestvideo[height<=480]+bestaudio/best", "--merge-output-format", "mp4"],
    "Audio only (MP3)": [
        "-f", "bestaudio/best", "--extract-audio",
        "--audio-format", "mp3", "--audio-quality", "192k",
    ],
}

THEMES = {
    "light": {
        "bg": "#F4F5F7",
        "card": "#FFFFFF",
        "text": "#1A1A1A",
        "muted": "#5C6570",
        "accent": "#E11D48",
        "border": "#D8DEE6",
        "ok": "#15803D",
        "log_bg": "#FAFBFC",
        "trough": "#E8ECF0",
        "entry_bg": "#FFFFFF",
        "entry_fg": "#1A1A1A",
    },
    "dark": {
        "bg": "#12151A",
        "card": "#1C2128",
        "text": "#E8EAED",
        "muted": "#9AA3AD",
        "accent": "#FB7185",
        "border": "#2F3843",
        "ok": "#4ADE80",
        "log_bg": "#161B22",
        "trough": "#2A323C",
        "entry_bg": "#0F1318",
        "entry_fg": "#E8EAED",
    },
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


def looks_like_video_url(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    return any(
        h in host
        for h in ("youtube.com", "youtu.be", "youtube-nocookie.com", "music.youtube.com")
    )


def load_settings() -> dict:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_settings(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def detect_system_theme() -> str:
    """Return 'dark' or 'light' from macOS appearance when possible."""
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and "Dark" in (result.stdout or ""):
            return "dark"
    except Exception:
        pass
    return "light"


class YouTubeDownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = load_settings()
        saved = self.settings.get("theme")
        if saved in ("light", "dark"):
            self.theme_name = saved
        else:
            self.theme_name = detect_system_theme()
        self.colors = THEMES[self.theme_name]

        self.root.title(APP_NAME)
        self.root.geometry("740x680")
        self.root.minsize(640, 580)
        self.root.configure(bg=self.colors["bg"])

        self.yt_dlp = resolve_tool("yt-dlp")
        self.ffmpeg = resolve_tool("ffmpeg")

        self.url = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(DEFAULT_DIR))
        self.quality = tk.StringVar(value="Best available")
        self.status = tk.StringVar(value="Paste a YouTube link to get started")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.theme_label = tk.StringVar(
            value="Dark mode" if self.theme_name == "light" else "Light mode"
        )

        self.busy = False
        self.proc: subprocess.Popen[str] | None = None
        self.log_q: queue.Queue[tuple[str, str]] = queue.Queue()

        self._style = ttk.Style()
        self._apply_theme_styles()
        self._build()
        self._bind_keys()
        self._refresh_deps()
        self.root.after(100, self._drain_log)
        self.url_entry.focus_set()

    def _apply_theme_styles(self) -> None:
        c = self.colors
        style = self._style
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=c["bg"])
        style.configure("Card.TFrame", background=c["card"])
        style.configure("TLabel", background=c["bg"], foreground=c["text"], font=("Helvetica Neue", 12))
        style.configure(
            "Title.TLabel",
            background=c["bg"],
            foreground=c["text"],
            font=("Helvetica Neue", 22, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=c["bg"],
            foreground=c["muted"],
            font=("Helvetica Neue", 11),
        )
        style.configure(
            "Card.TLabel",
            background=c["card"],
            foreground=c["text"],
            font=("Helvetica Neue", 12),
        )
        style.configure(
            "CardMuted.TLabel",
            background=c["card"],
            foreground=c["muted"],
            font=("Helvetica Neue", 11),
        )
        style.configure(
            "Status.TLabel",
            background=c["bg"],
            foreground=c["muted"],
            font=("Helvetica Neue", 11),
        )
        style.configure("TButton", font=("Helvetica Neue", 12), padding=(12, 8))
        style.configure("Accent.TButton", font=("Helvetica Neue", 13, "bold"), padding=(16, 10))
        style.configure(
            "TEntry",
            padding=8,
            fieldbackground=c["entry_bg"],
            foreground=c["entry_fg"],
            insertcolor=c["text"],
        )
        style.configure(
            "TCombobox",
            padding=6,
            fieldbackground=c["entry_bg"],
            foreground=c["entry_fg"],
            background=c["card"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["entry_bg"])],
            foreground=[("readonly", c["entry_fg"])],
        )
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=c["trough"],
            background=c["accent"],
            bordercolor=c["border"],
            lightcolor=c["accent"],
            darkcolor=c["accent"],
        )

    def _build(self) -> None:
        self.shell = ttk.Frame(self.root, padding=20)
        self.shell.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(self.shell)
        header.pack(fill=tk.X, pady=(0, 14))
        left_h = ttk.Frame(header)
        left_h.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(left_h, text=APP_NAME, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            left_h,
            text=f"by Shahzaib · macOS · Intel & Apple Silicon · {platform.machine()}",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 0))
        self.theme_btn = ttk.Button(
            header, textvariable=self.theme_label, command=self._toggle_theme, width=12
        )
        self.theme_btn.pack(side=tk.RIGHT, anchor=tk.N)

        self.card = tk.Frame(
            self.shell,
            bg=self.colors["card"],
            highlightbackground=self.colors["border"],
            highlightthickness=1,
            bd=0,
        )
        self.card.pack(fill=tk.X, pady=(0, 14))
        inner = ttk.Frame(self.card, style="Card.TFrame", padding=18)
        inner.pack(fill=tk.X)

        ttk.Label(inner, text="Video or playlist URL", style="CardMuted.TLabel").pack(anchor=tk.W)
        url_row = ttk.Frame(inner, style="Card.TFrame")
        url_row.pack(fill=tk.X, pady=(6, 12))
        self.url_entry = ttk.Entry(url_row, textvariable=self.url, font=("Menlo", 13))
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        ttk.Button(url_row, text="Paste", command=self._paste).pack(side=tk.LEFT, padx=(8, 0))

        opts = ttk.Frame(inner, style="Card.TFrame")
        opts.pack(fill=tk.X, pady=(0, 12))
        opts.columnconfigure(0, weight=1)
        opts.columnconfigure(1, weight=1)

        left = ttk.Frame(opts, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(left, text="Quality", style="CardMuted.TLabel").pack(anchor=tk.W)
        self.quality_box = ttk.Combobox(
            left,
            textvariable=self.quality,
            values=list(QUALITY_OPTIONS.keys()),
            state="readonly",
            font=("Helvetica Neue", 12),
        )
        self.quality_box.pack(fill=tk.X, pady=(6, 0), ipady=2)

        right = ttk.Frame(opts, style="Card.TFrame")
        right.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(right, text="Save folder", style="CardMuted.TLabel").pack(anchor=tk.W)
        dir_row = ttk.Frame(right, style="Card.TFrame")
        dir_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Entry(dir_row, textvariable=self.out_dir, font=("Helvetica Neue", 11)).pack(
            side=tk.LEFT, fill=tk.X, expand=True, ipady=3
        )
        ttk.Button(dir_row, text="Browse", command=self._browse).pack(side=tk.LEFT, padx=(8, 0))

        actions = ttk.Frame(inner, style="Card.TFrame")
        actions.pack(fill=tk.X, pady=(4, 0))
        self.download_btn = ttk.Button(
            actions, text="Download", style="Accent.TButton", command=self._start_download
        )
        self.download_btn.pack(side=tk.LEFT)
        self.cancel_btn = ttk.Button(actions, text="Cancel", command=self._cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Open folder", command=self._open_folder).pack(side=tk.LEFT, padx=(8, 0))
        self.fix_btn = ttk.Button(actions, text="Fix tools", command=self._install_tools)
        self.fix_btn.pack(side=tk.RIGHT)

        ttk.Label(self.shell, textvariable=self.status, style="Status.TLabel").pack(
            anchor=tk.W, pady=(0, 6)
        )
        self.progress = ttk.Progressbar(
            self.shell,
            mode="determinate",
            maximum=100,
            variable=self.progress_value,
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill=tk.X, pady=(0, 12))

        log_header = ttk.Frame(self.shell)
        log_header.pack(fill=tk.X)
        ttk.Label(log_header, text="Activity", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Button(log_header, text="Clear", command=self._clear_log).pack(side=tk.RIGHT)

        self.log_wrap = tk.Frame(
            self.shell,
            bg=self.colors["card"],
            highlightbackground=self.colors["border"],
            highlightthickness=1,
        )
        self.log_wrap.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.log = tk.Text(
            self.log_wrap,
            wrap=tk.WORD,
            font=("Menlo", 11),
            bg=self.colors["log_bg"],
            fg=self.colors["text"],
            relief=tk.FLAT,
            padx=12,
            pady=10,
            highlightthickness=0,
            borderwidth=0,
            insertbackground=self.colors["text"],
        )
        scroll = ttk.Scrollbar(self.log_wrap, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._apply_log_tags()

    def _apply_log_tags(self) -> None:
        self.log.tag_configure("ok", foreground=self.colors["ok"])
        self.log.tag_configure("err", foreground=self.colors["accent"])
        self.log.tag_configure("muted", foreground=self.colors["muted"])

    def _toggle_theme(self) -> None:
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.colors = THEMES[self.theme_name]
        self.theme_label.set("Dark mode" if self.theme_name == "light" else "Light mode")
        self.settings["theme"] = self.theme_name
        save_settings(self.settings)
        self._recolor()

    def _recolor(self) -> None:
        c = self.colors
        self.root.configure(bg=c["bg"])
        self._apply_theme_styles()
        self.card.configure(bg=c["card"], highlightbackground=c["border"])
        self.log_wrap.configure(bg=c["card"], highlightbackground=c["border"])
        self.log.configure(bg=c["log_bg"], fg=c["text"], insertbackground=c["text"])
        self._apply_log_tags()

    def _bind_keys(self) -> None:
        self.root.bind("<Return>", lambda _e: self._start_download())
        self.root.bind("<Escape>", lambda _e: self._cancel())
        self.root.bind("<Command-v>", lambda _e: self._paste())
        self.root.bind("<Control-v>", lambda _e: self._paste())
        self.root.bind("<Command-d>", lambda _e: self._toggle_theme())
        self.root.bind("<Control-d>", lambda _e: self._toggle_theme())

    def _refresh_deps(self) -> None:
        self.yt_dlp = resolve_tool("yt-dlp")
        self.ffmpeg = resolve_tool("ffmpeg")
        if self.yt_dlp and self.ffmpeg:
            self.status.set("Ready — paste a link and click Download")
            self.download_btn.configure(state=tk.NORMAL)
            self._append(f"Shahzaib YouTube Downloader · {platform.machine()} · {self.theme_name} theme", "ok")
            self._append(f"yt-dlp: {self.yt_dlp}", "muted")
            self._append(f"ffmpeg: {self.ffmpeg}", "muted")
        else:
            missing = [n for n, p in (("yt-dlp", self.yt_dlp), ("ffmpeg", self.ffmpeg)) if not p]
            self.status.set(f"Missing {', '.join(missing)} — click Fix tools")
            self.download_btn.configure(state=tk.DISABLED)
            self._append("Tools missing. Click “Fix tools” or run ./install.sh", "err")

    def _paste(self) -> None:
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            return
        if text:
            self.url.set(text)
            self.url_entry.icursor(tk.END)

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.out_dir.get() or str(DEFAULT_DIR))
        if chosen:
            self.out_dir.set(chosen)

    def _open_folder(self) -> None:
        path = Path(self.out_dir.get()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(path)], check=False)

    def _clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def _append(self, line: str, tag: str = "") -> None:
        self.log_q.put((line.rstrip(), tag))

    def _drain_log(self) -> None:
        while True:
            try:
                line, tag = self.log_q.get_nowait()
            except queue.Empty:
                break
            if tag:
                self.log.insert(tk.END, line + "\n", tag)
            else:
                self.log.insert(tk.END, line + "\n")
            self.log.see(tk.END)
            match = PROGRESS_RE.search(line)
            if match:
                try:
                    self.progress_value.set(float(match.group(1)))
                except ValueError:
                    pass
        self.root.after(80, self._drain_log)

    def _install_tools(self) -> None:
        if self.busy:
            return
        brew = resolve_tool("brew") or shutil.which("brew")
        if not brew:
            messagebox.showerror(
                "Homebrew required",
                "Homebrew is not installed.\n\nInstall from https://brew.sh then click Fix tools again.",
            )
            return
        self.busy = True
        self.download_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.DISABLED)
        self.fix_btn.configure(state=tk.DISABLED)
        self.status.set("Installing yt-dlp and ffmpeg…")
        self.progress_value.set(0)
        self._append("Running: brew install yt-dlp ffmpeg", "muted")

        def worker() -> None:
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
                    self._append(line.rstrip(), "muted")
                code = proc.wait()
                if code == 0:
                    self._append("Tools installed successfully.", "ok")
                    self.root.after(0, lambda: self.status.set("Tools ready"))
                else:
                    self._append(f"brew failed with code {code}", "err")
                    self.root.after(0, lambda: self.status.set("Install failed — see Activity"))
            except Exception as exc:  # noqa: BLE001
                self._append(str(exc), "err")
            finally:
                self.root.after(0, self._after_fix)

        threading.Thread(target=worker, daemon=True).start()

    def _after_fix(self) -> None:
        self.busy = False
        self.fix_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)
        self._refresh_deps()

    def _start_download(self) -> None:
        if self.busy:
            return
        if not self.yt_dlp or not self.ffmpeg:
            if messagebox.askyesno("Tools needed", "yt-dlp / ffmpeg missing. Install now?"):
                self._install_tools()
            return

        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Paste a YouTube video or playlist link.")
            return
        if not looks_like_video_url(url):
            if not messagebox.askyesno(
                "Unusual link",
                "This does not look like a YouTube URL.\nContinue anyway?",
            ):
                return

        out = Path(self.out_dir.get()).expanduser()
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder error", str(exc))
            return

        fmt = QUALITY_OPTIONS.get(self.quality.get(), QUALITY_OPTIONS["Best available"])
        cmd = [
            self.yt_dlp,
            "--newline",
            "--no-colors",
            "--progress",
            "--ffmpeg-location",
            str(Path(self.ffmpeg).parent),
            "-o",
            str(out / "%(title)s.%(ext)s"),
            *fmt,
            url,
        ]

        self.busy = True
        self.download_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.fix_btn.configure(state=tk.DISABLED)
        self.progress_value.set(0)
        self.status.set("Downloading…")
        self._append("")
        self._append(f"Downloading: {url}", "ok")
        self._append(f"Quality: {self.quality.get()} → {out}", "muted")

        threading.Thread(target=self._run, args=(cmd,), daemon=True).start()

    def _run(self, cmd: list[str]) -> None:
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self._append(line.rstrip())
            code = self.proc.wait()
            if code == 0:
                self.progress_value.set(100)
                self._append("Download finished.", "ok")
                self.root.after(0, lambda: self.status.set("Done — file saved in your folder"))
                self.root.after(
                    0,
                    lambda: messagebox.showinfo("Done", "Download finished successfully."),
                )
            elif self.busy:
                self._append(f"Failed (exit {code}). Check the link and try again.", "err")
                self.root.after(0, lambda: self.status.set("Download failed — see Activity"))
            else:
                self._append("Cancelled.", "muted")
                self.root.after(0, lambda: self.status.set("Cancelled"))
        except Exception as exc:  # noqa: BLE001
            self._append(str(exc), "err")
            self.root.after(0, lambda: self.status.set(f"Error: {exc}"))
        finally:
            self.proc = None
            self.root.after(0, self._reset_ui)

    def _cancel(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.busy = False
            self.proc.terminate()
            self.status.set("Cancelling…")

    def _reset_ui(self) -> None:
        self.busy = False
        self.download_btn.configure(state=tk.NORMAL if self.yt_dlp and self.ffmpeg else tk.DISABLED)
        self.cancel_btn.configure(state=tk.DISABLED)
        self.fix_btn.configure(state=tk.NORMAL)


def main() -> None:
    ensure_path()
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.0)
    except tk.TclError:
        pass
    YouTubeDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
