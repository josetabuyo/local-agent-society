#!/bin/bash
SYSTEM_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# ── backend ───────────────────────────────────────────────────────────────────
bash "$SYSTEM_DIR/backend/start.sh"

# ── widget ────────────────────────────────────────────────────────────────────
if pgrep -f "widget System" > /dev/null 2>&1; then
    echo "Widget     → ya corriendo"
else
    "$SYSTEM_DIR/widget/widget" System "HAIKU · SONNET · OPUS" &
    echo "Widget     → lanzado"
fi

# ── haiku watcher ─────────────────────────────────────────────────────────────
if pgrep -f "haiku-watcher.sh" > /dev/null 2>&1; then
    echo "Haiku      → ya corriendo"
else
    nohup bash "$SYSTEM_DIR/session/haiku-watcher.sh" \
        >> "$SYSTEM_DIR/session/haiku-watcher.log" 2>&1 &
    echo "Haiku      → lanzado (PID $!)"
fi

# ── opus watcher ──────────────────────────────────────────────────────────────
if pgrep -f "opus-watcher.sh" > /dev/null 2>&1; then
    echo "Opus       → ya corriendo"
else
    nohup bash "$SYSTEM_DIR/session/opus-watcher.sh" \
        >> "$SYSTEM_DIR/session/opus-watcher.log" 2>&1 &
    echo "Opus       → lanzado (PID $!)"
fi

echo ""
echo "Sistema listo. Sonnet: habla con esta sesión de Claude."
