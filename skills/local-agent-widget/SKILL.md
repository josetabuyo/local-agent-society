---
name: local-agent-widget
description: Open or focus the widget for the local agent in the current directory.
allowed-tools: Bash(python3:*)
---

# /local-agent-widget — Reopen the widget on the current Space

Closes the existing widget wherever it is and reopens it on the active Space.
Reads the agent name from `.las-agent.json` in the current directory automatically (`.agent.json` is read as a fallback for agents not yet migrated).

## Steps

### 1. Reopen the widget
```bash
PATH="$HOME/.local/bin:$PATH" las widget
```

`las widget` reads the agent config in the CWD and reopens the widget via the `localagentsociety://` URL scheme.
Pass a name explicitly to target a different agent: `PATH="$HOME/.local/bin:$PATH" las widget HomeControl`.
To reopen ALL agent widgets at once: `PATH="$HOME/.local/bin:$PATH" las widgets`.

If no agent config file exists, tell the user to run `las agent new NAME` first.

Report: "Widget reopened on this Space."

## Widget controls reference

| Button | Tap | Drag |
|--------|-----|------|
| ⚙ Gear | Expand/collapse config panel | — |
| ⊙ Scope | Focus agent terminal | Drop on any terminal to link it via `las link` |
| ⧉ Open | Run the default open action (terminal window at the agent's folder, out of the box) | Long-press / right-click: pick Terminal or Folder, ▲ ▼ to reorder (top = default) |
| 🎤 Mic | Toggle voice input | Long-press: change language |
| 🔊 Speaker | Mute/unmute TTS | Long-press: speaker options |

### Linking a terminal (scope drag)
Drag the ⊙ scope button onto any open terminal. The widget pastes `las link --agent NAME` and presses Enter. The widget flashes green when linked. The linked TTY receives all voice and text injections.

### Open button (replaced the command palette)
- **Terminal**: a new window of the default terminal (Ghostty on this machine, else iTerm2, else Terminal.app) with its shell in the agent's folder — the one holding `.las-agent.json`, as registered on the backend.
- **Folder**: that folder in Finder.
- Click = the top action. Hold or right-click = the menu; ▲ ▼ reorder, and the order is saved per agent.
