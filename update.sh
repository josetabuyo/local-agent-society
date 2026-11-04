#!/bin/bash
# `las update` — the whole flow lives in cli/updater.py (stdlib only): it
# pulls, re-execs the freshly pulled copy of itself, runs stop → install →
# start → normalize quietly (full output in ~/.las/logs/update-*.log) and
# prints what's new. exec on the first line that runs, so a pull that
# rewrites this file can never confuse bash mid-read.
INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$INSTALL_DIR/cli/updater.py" "$@"
