#!/bin/bash
# Local Agent Society — uninstaller
set -e

INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Local Agent Society — desinstalando"

launchctl unload ~/Library/LaunchAgents/com.localagent.system.plist       2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.localagent.system.haiku.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.localagent.system.opus.plist  2>/dev/null || true

rm -f ~/Library/LaunchAgents/com.localagent.system.plist
rm -f ~/Library/LaunchAgents/com.localagent.system.haiku.plist
rm -f ~/Library/LaunchAgents/com.localagent.system.opus.plist

pkill -f "haiku-watcher.sh" 2>/dev/null || true
pkill -f "opus-watcher.sh"  2>/dev/null || true
pkill -x tray               2>/dev/null || true

echo "Listo. Los datos en $INSTALL_DIR no fueron eliminados."
