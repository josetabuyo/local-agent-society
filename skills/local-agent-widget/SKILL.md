---
name: local-agent-widget
description: Open or focus the widget for the local agent in the current directory.
allowed-tools: Bash(python3:*) Bash(open:*)
---

# /local-agent-widget — Open or focus the widget for this agent

Reads `.agent.json` in the current directory and sends `open localagentsociety://<name>` to the running tray app.

## Steps

### 1. Read agent name from .agent.json
```bash
python3 -c "import json; print(json.load(open('.agent.json'))['name'])"
```

### 2. Open/focus the widget
```bash
open "localagentsociety://NAME"
```

If `.agent.json` doesn't exist, tell the user to run `/new-local-agent` first.

Report: "Widget opened for NAME."
