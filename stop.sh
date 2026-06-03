#!/bin/bash
SYSTEM_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SYSTEM_DIR/backend/backend.pid"

# ── backend ───────────────────────────────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" && echo "Backend    → stopped (PID $PID)"
    else
        echo "Backend    → not running"
    fi
    rm "$PID_FILE"
else
    # Fallback: kill by port
    PID=$(lsof -ti tcp:8700 2>/dev/null)
    if [ -n "$PID" ]; then
        kill $PID && echo "Backend    → stopped (PID $PID)"
    else
        echo "Backend    → not running"
    fi
fi

# ── tray app ──────────────────────────────────────────────────────────────────
if pgrep -x "tray" > /dev/null 2>&1; then
    pkill -x "tray" && echo "Society    → stopped"
else
    echo "Society    → not running"
fi
