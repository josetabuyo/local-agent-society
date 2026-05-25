#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SCRIPT_DIR/backend.pid"
LOG_FILE="$SCRIPT_DIR/backend.log"
PORT=8700

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Backend already running on http://localhost:$PORT (PID $PID)"
        exit 0
    else
        rm "$PID_FILE"
    fi
fi

pip3 install -q fastapi "uvicorn[standard]" 2>/dev/null

cd "$SCRIPT_DIR"
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port $PORT > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 1

if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "Backend started → http://localhost:$PORT  (PID $(cat $PID_FILE))"
    echo "Docs          → http://localhost:$PORT/docs"
    echo "Log           → $LOG_FILE"
else
    echo "ERROR: backend failed to start — check $LOG_FILE"
    rm "$PID_FILE"
    exit 1
fi
