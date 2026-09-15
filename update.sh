#!/bin/bash
set -e
INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Local Agent Society — updating"

git -C "$INSTALL_DIR" pull

bash "$INSTALL_DIR/stop.sh"

# install.sh also pulls the vortexia sibling repo (a dependency, not part
# of this repo) — no separate step needed here for it.
bash "$INSTALL_DIR/install.sh"
bash "$INSTALL_DIR/start.sh"
