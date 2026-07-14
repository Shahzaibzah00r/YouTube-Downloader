#!/usr/bin/env python3
"""YouTube Downloader — polished GUI for Intel and Apple Silicon Macs."""

from __future__ import annotations

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
PROGRESS_RE = re.compile(r"\[download\]\s+([0-9.]+)%")

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

COLORS = {
    "bg": "#F4F5F7",
    "card": "#FFFFFF",
    "text": "#1A1A1A",
    "muted": "#5C6570",
    "accent": "#E11D48",
    "accent_hover": "#BE123C",
    "border": "#D8DEE6",
    "ok": "#15803D",
    "warn": "#B45309",
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


class YouTubeDownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("YouTube Downloader")
        self.root.geometry("720x640")
        self.root.minsize(640, 560)
        self.root.configure(bg=COLORS["bg"])

        self.yt_dlp = resolve_tool("yt-dlp")
        self.ffmpeg = resolve_tool("ffmpeg")

        self.url = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(DEFAULT_DIR))
        self.quality = tk.StringVar(value="Best available")
        self.status = tk.StringVar(value="Paste a YouTube link to get started")
        self.progress_value = tk.DoubleVar(value=0.0)

        self.busy = False
        self.proc: subprocess.Popen[str] | None = None
        self.log_q: queue.Queue[tuple[str, str]] = queue.Queue()

        self._style()
        self._build()
        self._bind_keys()
        self._refresh_deps()
        self.root.after(100, self._drain_log)
        self.url_entry.focus_set()

    def _style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Card.TFrame", background=COLORS["card"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Helvetica Neue", 12))
        style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Helvetica Neue", 22, "bold"))
        style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Helvetica Neue", 11))
        style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"], font=("Helvetica Neue", 12))
        style.configure("CardMuted.TLabel", background=COLORS["card"], foreground=COLORS["muted"], font=("Helvetica Neue", 11))
        style.configure("Status.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Helvetica Neue", 11))
        style.configure("TButton", font=("Helvetica Neue", 12), padding=(12, 8))
        style.configure("Accent.TButton", font=("Helvetica Neue", 13, "bold"), padding=(16, 10))
        style.configure("TEntry", padding=8, fieldbackground="#FFFFFF")
        style.configure("TCombobox", padding=6)
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor="#E8ECF0",
            background=COLORS["accent"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
        )

    def _build(self) -> None:
        shell = ttk.Frame(self.root, padding=20)
        shell.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(shell)
        header.pack(fill=tk.X, pady=(0, 14))
        ttk.Label(header, text="YouTube Downloader", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            header,
            text=f"macOS · Intel & Apple Silicon · {platform.machine()}",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 0))

        card = tk.Frame(
            shell,
            bg=COLORS["card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            bd=0,
        )
        card.pack(fill=tk.X, pady=(0, 14))
        inner = ttk.Frame(card, style="Card.TFrame", padding=18)
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

        ttk.Label(shell, textvariable=self.status, style="Status.TLabel").pack(anchor=tk.W, pady=(0, 6))
        self.progress = ttk.Progressbar(
            shell,
            mode="determinate",
            maximum=100,
            variable=self.progress_value,
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill=tk.X, pady=(0, 12))

        log_header = ttk.Frame(shell)
        log_header.pack(fill=tk.X)
        ttk.Label(log_header, text="Activity", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Button(log_header, text="Clear", command=self._clear_log).pack(side=tk.RIGHT)

        log_wrap = tk.Frame(
            shell,
            bg=COLORS["card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        log_wrap.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.log = tk.Text(
            log_wrap,
            wrap=tk.WORD,
            font=("Menlo", 11),
            bg="#FAFBFC",
            fg=COLORS["text"],
            relief=tk.FLAT,
            padx=12,
            pady=10,
            highlightthickness=0,
            borderwidth=0,
        )
        scroll = ttk.Scrollbar(log_wrap, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.tag_configure("ok", foreground=COLORS["ok"])
        self.log.tag_configure("err", foreground=COLORS["accent"])
        self.log.tag_configure("muted", foreground=COLORS["muted"])

    def _bind_keys(self) -> None:
        self.root.bind("<Return>", lambda _e: self._start_download())
        self.root.bind("<Escape>", lambda _e: self._cancel())
        self.root.bind("<Command-v>", lambda _e: self._paste())
        self.root.bind("<Control-v>", lambda _e: self._paste())

    def _refresh_deps(self) -> None:
        self.yt_dlp = resolve_tool("yt-dlp")
        self.ffmpeg = resolve_tool("ffmpeg")
        if self.yt_dlp and self.ffmpeg:
            self.status.set("Ready — paste a link and click Download")
            self.download_btn.configure(state=tk.NORMAL)
            self._append(f"Ready on {platform.machine()}", "ok")
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
    # Do not force tk scaling — it breaks layout on many Macs.
    try:
        # Prefer a crisp default window on Retina without overscaling widgets.
        root.tk.call("tk", "scaling", 1.0)
    except tk.TclError:
        pass
    YouTubeDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
