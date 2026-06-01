#!/usr/bin/env python3
"""
Migrate .agent.json files from the old schema to the current one.

Old schema:  agent-family, role, members, voice, pronunciation, ...
New schema:  name, voice, pronunciation, backend_url, frontend_url, created

Usage:
    python3 migrate-agent-json.py                  # scan from ~/Development
    python3 migrate-agent-json.py /path/to/scan    # scan from a specific root
    python3 migrate-agent-json.py --dry-run        # preview without writing
"""

import json
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
root = Path(args[0]).expanduser() if args else Path.home() / "Development"

REMOVE_KEYS = {"role", "members", "agent-family"}

found = list(root.rglob(".agent.json"))
if not found:
    print(f"No .agent.json files found under {root}")
    sys.exit(0)

changed = 0
for path in sorted(found):
    data = json.loads(path.read_text())

    # Already migrated
    if "name" in data and "agent-family" not in data and "role" not in data:
        print(f"  ok  {path}")
        continue

    # Build migrated copy
    new = {}
    new["name"] = data.get("agent-family") or data.get("name", "")
    for key in ("voice", "pronunciation", "backend_url", "frontend_url", "created"):
        if key in data:
            new[key] = data[key]

    if DRY_RUN:
        print(f"  ~~  {path}")
        print(f"      before: {list(data.keys())}")
        print(f"      after:  {list(new.keys())}")
    else:
        path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        print(f"  ✓   {path}")
    changed += 1

label = "would migrate" if DRY_RUN else "migrated"
print(f"\n{label}: {changed} / {len(found)} files")
