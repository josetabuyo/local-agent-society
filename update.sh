#!/bin/bash
set -e
INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Local Agent Society — updating"

git -C "$INSTALL_DIR" pull

pkill -f "Local Agent Society" 2>/dev/null || true
pkill -x tray 2>/dev/null || true

bash "$INSTALL_DIR/install.sh"
bash "$INSTALL_DIR/start.sh"
