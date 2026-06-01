#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SCRIPT_DIR/backend.pid"
LOG_FILE="$SCRIPT_DIR/backend.log"
PORT=8700

if lsof -ti tcp:$PORT > /dev/null 2>&1; then
    echo "Backend already running on http://localhost:$PORT"
    exit 0
fi

if [ -f "$PID_FILE" ]; then
    rm "$PID_FILE"
fi

VENV="$SCRIPT_DIR/.venv"
if [ ! -f "$VENV/bin/pip" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q fastapi "uvicorn[standard]"

cd "$SCRIPT_DIR"
nohup "$VENV/bin/python" -m uvicorn main:app --host 0.0.0.0 --port $PORT > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 2

if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "Backend started → http://localhost:$PORT  (PID $(cat $PID_FILE))"
    echo "Docs          → http://localhost:$PORT/docs"
    echo "Log           → $LOG_FILE"
else
    echo "ERROR: backend failed to start. Last log lines:"
    tail -5 "$LOG_FILE" 2>/dev/null || echo "  (no log file)"
    rm "$PID_FILE"
    exit 1
fi
