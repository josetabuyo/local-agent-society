#!/bin/bash
set -e
INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Local Agent Society — updating"

git -C "$INSTALL_DIR" pull

bash "$INSTALL_DIR/stop.sh"

# install.sh also pulls the vortexia sibling repo (a dependency, not part
# of this repo) — no separate step needed here for it.
bash "$INSTALL_DIR/install.sh"

# Agent configs: .las-agent.json is the only name read (docs/adr/0001
# addendum) — migrate any pre-rename .agent.json left on this machine.
DEV_ROOT="$( cd "$INSTALL_DIR/.." && pwd )"
if [ -n "$(find "$DEV_ROOT" -maxdepth 5 -name .agent.json -not -path '*/node_modules/*' -print -quit 2>/dev/null)" ]; then
    echo "Migrating legacy .agent.json files..."
    python3 "$INSTALL_DIR/scripts/migrate-agent-json.py" "$DEV_ROOT" || echo "  ⚠️  migration failed — run scripts/migrate-agent-json.py by hand"
fi

bash "$INSTALL_DIR/start.sh"

# Bring every agent's .las-agent.json to the canonical shape (fills what is
# missing, never overwrites). Needs the backend, which start.sh brought up.
for _ in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://localhost:8700/health >/dev/null && break; sleep 1; done
las agent normalize --all || echo "  ⚠️  las agent normalize --all failed — run it by hand"
