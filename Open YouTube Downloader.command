#!/bin/bash
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
exec /usr/bin/env python3 "$(dirname "$0")/youtube_downloader_gui.py"
