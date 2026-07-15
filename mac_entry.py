#!/usr/bin/env python3
"""App bundle entry — starts YTDownloader per pywebview's recommended usage.

See: https://pywebview.flowrl.com/guide/usage
     https://pywebview.flowrl.com/guide/installation.html (macOS PyObjC)
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

RES = Path(__file__).resolve().parent
LOG_DIR = Path.home() / "Library" / "Logs" / "YTDownloader"
LOG_FILE = LOG_DIR / "launch.log"


def _log(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(msg.rstrip() + "\n")
    except Exception:
        pass


def _fatal(message: str) -> None:
    """Show an error without going through osascript (avoids Script Editor)."""
    _log(f"FATAL: {message}")
    try:
        # Prefer Cocoa alert so the message belongs to this Python process
        from AppKit import NSAlert, NSApplication, NSInformationalAlertStyle  # type: ignore

        NSApplication.sharedApplication()
        alert = NSAlert.alloc().init()
        alert.setMessageText_("YTDownloader")
        alert.setInformativeText_(message)
        alert.setAlertStyle_(NSInformationalAlertStyle)
        alert.addButtonWithTitle_("OK")
        alert.runModal()
    except Exception:
        try:
            # Last resort: open the log in TextEdit
            os.system(f'open -a TextEdit "{LOG_FILE}"')  # noqa: S605
        except Exception:
            pass
    raise SystemExit(1)


def main() -> None:
    os.chdir(RES)
    if str(RES) not in sys.path:
        sys.path.insert(0, str(RES))

    _log(f"---- entry {__file__} py={sys.version.split()[0]} ----")

    # Official macOS deps for pywebview (stand-alone Python / Homebrew)
    try:
        import webview  # noqa: F401
        import AppKit  # noqa: F401
        import WebKit  # noqa: F401
    except ImportError as exc:
        _fatal(
            "Native window libraries are missing.\n\n"
            f"{exc}\n\n"
            "Quit the app, then reinstall with the curl installer "
            "(or delete ~/Library/Application Support/YTDownloader/venv "
            "and open again).\n\n"
            f"Log: {LOG_FILE}"
        )

    try:
        from yt_downloader import main as app_main

        app_main()
    except SystemExit:
        raise
    except Exception:
        _log(traceback.format_exc())
        _fatal(
            "YTDownloader crashed while starting.\n\n"
            f"Details were written to:\n{LOG_FILE}"
        )


if __name__ == "__main__":
    main()
