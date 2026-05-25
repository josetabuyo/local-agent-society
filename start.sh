#!/bin/bash
SYSTEM_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# ── backend ───────────────────────────────────────────────────────────────────
bash "$SYSTEM_DIR/backend/start.sh"

# ── Local Agent Society (manages all widget windows) ─────────────────────────
if pgrep -x "tray" > /dev/null 2>&1; then
    echo "Society    → ya corriendo"
else
    open "$SYSTEM_DIR/widget/Local Agent Society.app"
    echo "Society    → lanzado"
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
