#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SCRIPT_DIR/backend.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "Backend not running (no PID file)"
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill "$PID" 2>/dev/null; then
    echo "Backend stopped (PID $PID)"
    rm "$PID_FILE"
else
    echo "Process $PID not found — cleaning up"
    rm "$PID_FILE"
fi
