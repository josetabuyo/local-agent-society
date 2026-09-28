#!/bin/bash
# Local Agent Society — uninstaller
set -e

INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Local Agent Society — desinstalando"

launchctl unload ~/Library/LaunchAgents/com.localagent.system.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.localagent.system.plist

pkill -x tray 2>/dev/null || true

# Claude Code's own config: drop the `las` channel server entry (docs/adr/0004).
command -v las >/dev/null 2>&1 && las claude unregister || true

echo "Listo. Los datos en $INSTALL_DIR no fueron eliminados."
