#!/bin/bash
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Prefer project venv (has pywebview for native Mac window)
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" "$ROOT/yt_downloader.py"
fi

# Create venv on first launch
PYTHON=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
  if [[ -x "$candidate" ]]; then PYTHON="$candidate"; break; fi
done

if [[ -z "$PYTHON" ]]; then
  osascript -e 'display dialog "Python 3 is required." buttons {"OK"} default button 1 with title "YTDownloader"'
  exit 1
fi

"$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -U pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
exec "$ROOT/.venv/bin/python" "$ROOT/yt_downloader.py"
