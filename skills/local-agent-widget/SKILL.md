---
name: local-agent-widget
description: Open or focus the widget for the local agent in the current directory.
allowed-tools: Bash(python3:*) Bash(open:*)
---

# /local-agent-widget — Reopen the widget on the current Space

Closes the existing widget wherever it is and reopens it on the active Space.
Reads the agent name from `.agent.json` in the current directory automatically.

## Steps

### 1. Read agent name from .agent.json
```bash
python3 -c "import json; print(json.load(open('.agent.json'))['name'])"
```
If `.agent.json` doesn't exist, tell the user to run `/new-local-agent` first.

### 2. Reopen the widget
```bash
open "localagentsociety://NAME?action=reopen"
```

Report: "Widget reopened on this Space for NAME."
