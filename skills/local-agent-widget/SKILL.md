---
name: local-agent-widget
description: Open or focus the widget for the local agent in the current directory.
allowed-tools: Bash(python3:*) Bash(open:*)
---

# /local-agent-widget — Reopen the widget on the current Space

Reads `.agent.json` in the current directory, closes the existing widget wherever it is, and reopens it on the active Space.

## Steps

### 1. Read agent name from .agent.json
```bash
python3 -c "import json; d=json.load(open('.agent.json')); print(d.get('name'))"
```

### 2. Reopen the widget on the current Space
```bash
open "localagentsociety://NAME?action=reopen"
```

If `.agent.json` doesn't exist, tell the user to run `/new-local-agent` first.

Report: "Widget reopened on this Space for NAME."
