#!/bin/bash
SYSTEM_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# ── backend ───────────────────────────────────────────────────────────────────
bash "$SYSTEM_DIR/backend/start.sh"

# ── Local Agent Society widget ────────────────────────────────────────────────
if pgrep -x "tray" > /dev/null 2>&1; then
    echo "Society    → ya corriendo"
else
    open "$SYSTEM_DIR/widget/Local Agent Society.app"
    echo "Society    → lanzado"
fi

echo ""
echo "Sistema listo. Abrí Claude Code en cualquier directorio con .agent.json."
