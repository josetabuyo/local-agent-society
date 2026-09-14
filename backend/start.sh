#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SCRIPT_DIR/backend.pid"
mkdir -p "$SCRIPT_DIR/logs"
# App-level diagnostics (e.g. vortexia connection issues) go through
# logging_config.py into logs/backend.log with daily rotation, 7-day
# retention. This raw stdout/stderr capture is only for output emitted
# before that's initialized, or a hard crash on the way down.
LOG_FILE="$SCRIPT_DIR/logs/launchd.out.log"
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
"$VENV/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

cd "$SCRIPT_DIR"
PYTHONPATH="$SCRIPT_DIR/.." nohup "$VENV/bin/python" -m uvicorn main:app --host 0.0.0.0 --port $PORT > "$LOG_FILE" 2>&1 &
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
