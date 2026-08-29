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

# ── widget (Electron) ────────────────────────────────────────────────────────
# Covers both the packaged app (process name matches the productName, "Local
# Agent Society") and a dev instance launched via `npm start`/`electron .`
# under widget-electron/ (process name "Electron", cwd under widget-electron).
FOUND=0
PACKAGED_PIDS=$(pgrep -f "Local Agent Society.app/Contents/MacOS/Local Agent Society" 2>/dev/null || true)
if [ -n "$PACKAGED_PIDS" ]; then
    kill $PACKAGED_PIDS 2>/dev/null && FOUND=1
fi
DEV_PIDS=$(pgrep -f "widget-electron" 2>/dev/null || true)
if [ -n "$DEV_PIDS" ]; then
    kill $DEV_PIDS 2>/dev/null && FOUND=1
fi

if [ "$FOUND" -eq 1 ]; then
    echo "Society    → stopped"
else
    echo "Society    → not running"
fi
