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
To reopen ALL agent widgets at once: `PATH="$HOME/.local/bin:$PATH" las widgets`.

If `.agent.json` doesn't exist, tell the user to run `/new-local-agent` first.

Report: "Widget reopened on this Space."

## Widget controls reference

| Button | Tap | Drag |
|--------|-----|------|
| ⚙ Gear | Expand/collapse config panel | — |
| ⊙ Scope | Focus agent terminal | Drop on any terminal to link it via `las link` |
| ⊞ Terminal | Open command palette | — |
| 🎤 Mic | Toggle voice input | Long-press: change language |
| 🔊 Speaker | Mute/unmute TTS | Long-press: speaker options |

### Linking a terminal (scope drag)
Drag the ⊙ scope button onto any open terminal. The widget pastes `las link --agent NAME` and presses Enter. The widget flashes green when linked. The linked TTY receives all voice and text injections.

### Command palette (terminal button)
- **Open terminal** items (⊠ icon): launch a new iTerm2 window with a Claude model.
- **Inject command** items: insert text into the linked session (e.g. `/clear`).
- Right side of each row: ▲ ▼ to reorder, ✏ to edit/delete.
- `+ Add command` at the bottom to create new entries.
