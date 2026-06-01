#!/bin/bash
# Foreground runner for launchd (KeepAlive). Do not use for manual dev starts — use start.sh.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PORT=8700

VENV="$SCRIPT_DIR/.venv"
if [ ! -f "$VENV/bin/pip" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q fastapi "uvicorn[standard]"

cd "$SCRIPT_DIR"
exec "$VENV/bin/python" -m uvicorn main:app --host 0.0.0.0 --port $PORT
