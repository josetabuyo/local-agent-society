---
name: local-agent-widget
description: Open or focus the widget for the local agent in the current directory.
allowed-tools: Bash(python3:*)
---

# /local-agent-widget — Reopen the widget on the current Space

Closes the existing widget wherever it is and reopens it on the active Space.
Reads the agent name from `.agent.json` in the current directory automatically.

## Steps

### 1. Reopen the widget
```bash
PATH="$HOME/.local/bin:$PATH" las widget
```

`las widget` reads `.agent.json` in the CWD and reopens the widget via the `localagentsociety://` URL scheme.
Pass a name explicitly to target a different agent: `PATH="$HOME/.local/bin:$PATH" las widget HomeControl`.

If `.agent.json` doesn't exist, tell the user to run `/new-local-agent` first.

Report: "Widget reopened on this Space."
