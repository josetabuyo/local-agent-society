#!/bin/bash
# Foreground runner for launchd (KeepAlive). Do not use for manual dev starts — use start.sh.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PORT=8700
mkdir -p "$SCRIPT_DIR/logs"

VENV="$SCRIPT_DIR/.venv"
if [ ! -f "$VENV/bin/pip" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

cd "$SCRIPT_DIR"
# main.py imports cli.path_utils at module level — needs the repo root on
# PYTHONPATH, same as start.sh sets for manual runs. Without this, every
# launchd-triggered start crashed on import and the job never stayed up
# (silently crash-looping under launchd's KeepAlive/ThrottleInterval).
export PYTHONPATH="$SCRIPT_DIR/.."
# This machine's federation identity (see backend/main.py's inject_message
# federation fallback and vortexia/docs/federation-poc.md) — must match the
# VORTEXIA_ENV_NAME vortexia itself is started with, and the other Mac's own
# env name ("uy-mac") for cross-machine exact-name resolution to agree on
# both sides. Confirmed with the System/Vortexia agents coordinating this.
export VORTEXIA_ENV_NAME="ba-mac"
exec "$VENV/bin/python" -m uvicorn main:app --host 0.0.0.0 --port $PORT
