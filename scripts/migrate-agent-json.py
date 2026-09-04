#!/usr/bin/env python3
"""
Migrate agent config files to the current filename and schema.

Changes applied:
  - Rename .agent.json -> .las-agent.json (skipped if a .las-agent.json
    already exists alongside it — that file wins, the stale .agent.json is
    left untouched rather than silently overwritten)
  - Rename report_max_chars -> response_length_hint (same value, meant as a
    soft target for THIS agent's own spoken summaries — never a hard
    truncation, and never applied to text the agent receives)
  - Add short_description / long_description if missing (default: "") —
    empty for now, meant to eventually back a vortexia intent-filter
    broadcast (who this agent is, what it offers, what it needs)
  - Remove `backend_url` and `frontend_url` (derived constants, not agent data)
  - Remove legacy keys: role, members, agent-family
  - Derive `name` from `agent-family` if missing

New canonical schema:
  {
    "name": "AgentName",
    "voice": "Samantha",
    "locale": "en-US",              # optional
    "pronunciation": "...",         # optional
    "created": "YYYY-MM-DD",
    "response_length_hint": 40,     # optional — soft length target for this
                                     # agent's own spoken summaries (not a
                                     # truncation, and not applied to
                                     # incoming text)
    "short_description": "",        # optional — filled in over time
    "long_description": "",         # optional — filled in over time
    "color": "#3A86FF",             # optional — widget background color (hex)
    "opacity": 0.92,                # optional — widget opacity 0.0–1.0
    "ports": [                      # optional — ports this agent has claimed
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
CARRY_KEYS = ("voice", "locale", "pronunciation", "created", "color", "opacity", "ports")
NEW_FILENAME = ".las-agent.json"
LEGACY_FILENAME = ".agent.json"

found = sorted(set(root.rglob(NEW_FILENAME)) | set(root.rglob(LEGACY_FILENAME)))
if not found:
    print(f"No agent config files found under {root}")
    sys.exit(0)

changed = 0
skipped = 0
for path in found:
    target = path.with_name(NEW_FILENAME)
    if path.name == LEGACY_FILENAME and target.exists():
        print(f"  --  {path} (skipped: {target} already exists)")
        skipped += 1
        continue

    data = json.loads(path.read_text())
    needs_rename = path.name == LEGACY_FILENAME
    needs_field_migration = (
        any(k in data for k in REMOVE_KEYS)
        or "report_max_chars" in data
        or "short_description" not in data
        or "long_description" not in data
    )

    if not needs_rename and not needs_field_migration:
        print(f"  ok  {path}")
        continue

    # Build migrated copy — preserve all keys except the ones we remove
    new = {}
    new["name"] = data.get("agent-family") or data.get("name", "")
    for key in CARRY_KEYS:
        if key in data:
            new[key] = data[key]
    new["response_length_hint"] = data.get("response_length_hint", data.get("report_max_chars", 40))
    new["short_description"] = data.get("short_description", "")
    new["long_description"] = data.get("long_description", "")

    if DRY_RUN:
        removed = [k for k in REMOVE_KEYS if k in data]
        action = f"{path.name} -> {NEW_FILENAME}" if needs_rename else "in place"
        print(f"  ~~  {path} ({action})")
        print(f"      remove: {removed}")
        print(f"      result: {list(new.keys())}")
    else:
        target.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        if needs_rename:
            path.unlink()
        print(f"  ✓   {target}")
    changed += 1

label = "would migrate" if DRY_RUN else "migrated"
print(f"\n{label}: {changed} / {len(found)} files ({skipped} skipped)")
