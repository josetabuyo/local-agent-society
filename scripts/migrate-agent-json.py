#!/usr/bin/env python3
"""
Migrate .agent.json files to the current schema.

Changes applied:
  - Remove `backend_url` and `frontend_url` (derived constants, not agent data)
  - Remove legacy keys: role, members, agent-family
  - Derive `name` from `agent-family` if missing

New canonical schema:
  {
    "name": "AgentName",
    "voice": "Samantha",
    "locale": "en-US",          # optional
    "pronunciation": "...",     # optional
    "created": "YYYY-MM-DD",
    "color": "#3A86FF",         # optional — widget background color (hex)
    "opacity": 0.92,            # optional — widget opacity 0.0–1.0
    "ports": [                  # optional — ports this agent has claimed
      {"port": 8765, "app": "frontend static server"},
      {"port": 8010, "app": "backend API"}
    ]
  }

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

REMOVE_KEYS = {"role", "members", "agent-family", "backend_url", "frontend_url"}

found = list(root.rglob(".agent.json"))
if not found:
    print(f"No .agent.json files found under {root}")
    sys.exit(0)

changed = 0
for path in sorted(found):
    data = json.loads(path.read_text())
    needs_migration = any(k in data for k in REMOVE_KEYS) or "agent-family" in data

    if not needs_migration:
        print(f"  ok  {path}")
        continue

    # Build migrated copy — preserve all keys except the ones we remove
    new = {}
    new["name"] = data.get("agent-family") or data.get("name", "")
    for key in ("voice", "locale", "pronunciation", "created", "color", "opacity", "ports"):
        if key in data:
            new[key] = data[key]

    if DRY_RUN:
        removed = [k for k in REMOVE_KEYS if k in data]
        print(f"  ~~  {path}")
        print(f"      remove: {removed}")
        print(f"      result: {list(new.keys())}")
    else:
        path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        print(f"  ✓   {path}")
    changed += 1

label = "would migrate" if DRY_RUN else "migrated"
print(f"\n{label}: {changed} / {len(found)} files")
