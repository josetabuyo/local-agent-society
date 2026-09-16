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
#
# Waits for the processes to actually exit before returning: a caller like
# update.sh runs electron-builder right after this to overwrite
# dist/mac-arm64/Local Agent Society.app, and `kill` alone only sends SIGTERM
# without waiting — helper processes (renderer/GPU) can still be shutting
# down and holding file handles into the bundle when the rebuild starts,
# corrupting the freshly-built .app so it silently fails to launch.
FOUND=0
WIDGET_PATTERN='Local Agent Society\.app/Contents/MacOS/Local Agent Society|widget-electron'
PIDS=$(pgrep -f "$WIDGET_PATTERN" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    FOUND=1
    kill $PIDS 2>/dev/null
    for _ in $(seq 1 20); do
        PIDS=$(pgrep -f "$WIDGET_PATTERN" 2>/dev/null || true)
        [ -z "$PIDS" ] && break
        sleep 0.25
    done
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null
        sleep 0.25
    fi
fi

if [ "$FOUND" -eq 1 ]; then
    echo "Society    → stopped"
else
    echo "Society    → not running"
fi
