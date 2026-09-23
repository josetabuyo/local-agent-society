# Local Agent Society

A coordination layer that turns Claude Code sessions into a **society of named agents** — each living in its own project folder, with a unique voice, a floating widget, and shared infrastructure for ports, TTS, and inter-agent messaging.

Every agent knows the rules. They never talk over each other. They never steal ports. They speak in their own language.

---

## What it does

- **Named agents** — each project directory registers as a named agent (`Wavi`, `Garantido`, `NeuroFlow`…) with its own identity and voice
- **Floating widget** — a macOS tray app shows the agent name on every Space, always on top, with mic input, mute, and config
- **Voice queue** — all TTS goes through a central queue so agents never collide when speaking; each voice has a fixed language
- **Port registry** — agents claim ports before binding; no hardcoded ports, no conflicts
- **Inject** — send a message directly into another agent's live Claude terminal
- **Attribution** — track which agent wrote which file

---

## Requirements

- macOS (arm64; Intel builds untested)
- Python 3.10+ (Homebrew), with `pipx` recommended for the `las` CLI
- Node.js 18+ (Electron widget and the vortexia broker)
- [Claude Code CLI](https://claude.ai/code)
- iTerm2 (agent focus/inject fallbacks use its AppleScript API)
- Network access on first install: `install.sh` clones the sibling
  [vortexia](https://github.com/haciendo/vortexia) repo next to this one and
  downloads the Kokoro TTS model (~340MB); the first mic dictation fetches
  Whisper (~140MB)

> **Status:** this is a developer checkout, not yet a double-click app. Everything
> (launchd jobs, the `las` CLI, the widget `.app`, data and models) lives inside the
> clone. See `docs/adr/0003-standalone-app-distribution.md` for the plan to change that.

---

## Install

```bash
git clone https://github.com/josetabuyo/local-agent-society
cd local-agent-society
./install.sh
```

This builds the Electron widget, installs Python deps, fetches the Kokoro TTS model, clones/updates vortexia next to this repo, registers both launchd jobs, and installs the `las` CLI.

---

## Create your first agent

In any project directory, run:

```
las agent new MyProject
```

The command writes `.las-agent.json`, registers the agent with the backend, assigns a unique voice (with its language), and opens the widget.

---

## The `las` CLI

### System
```
las status                              # backend status, agents, ports
las start / stop                        # start or stop the backend
las logs                                # tail backend log
las install                             # run install.sh (compile widget, launchd, CLI)
las uninstall                           # run uninstall.sh (remove the system)
las update                              # run update.sh (git pull + reinstall)
las completion [--shell zsh|bash|fish] [--install]  # set up shell tab completion
```

### Agents
```
las agents                              # list all registered agents
las agent new NAME [--voice V] [--dir D]  # write .las-agent.json, register, launch widget
las agent sync                          # sync .las-agent.json → backend
las agent restore [NAME]                # recover .las-agent.json from backend
las agent rename [OLD] NEW [--pronunciation P]  # rename in backend + update .las-agent.json
las agent focus [NAME]                  # bring the agent's iTerm2 window to the front
las agent inject NAME "msg"             # send message to another agent's terminal
las agent inject NAME "msg" --from Me   # with sender label
las agent clean [NAME]                  # inject /clear into agent terminal
las agent mute [NAME]                   # silence an agent's TTS
las agent unmute [NAME]                 # re-enable TTS
las agent deactivate [NAME]             # mark inactive, close its widget (session untouched)
las agent activate [NAME]               # mark active again
las agent wake-enable [NAME]            # allow `las agent focus` to wake it from inactive via vortexia
las agent wake-disable [NAME]           # disallow the auto-wake fallback above
las agent delete [NAME] [--yes]         # unregister from backend
las agents --inactive                   # list only inactive (put-away) agents
las agents --active                     # list only active agents
las widget [NAME]                       # reopen one agent's floating widget (new position, keeps color/prefs)
las widgets                             # reopen every registered agent's widget
las link [--agent NAME] [--tty PATH]    # link the current (or given) terminal to a widget
```
`NAME` is optional on most `agent` subcommands — it defaults to the agent registered for the current directory (via `.las-agent.json` or a path match in the backend registry).

`las agent focus` also acts as the wake-up path: if an agent has no live terminal session, is marked inactive, and has `wake-enable`d, it opens a new iTerm2 window running `claude --dangerously-skip-permissions` in the agent's directory and marks it active again — instead of just reporting "not found".

### Voices
```
las voices list                         # all voices with language flag
las voices info Samantha                # language info for one voice
las voices random                       # pick a random unused voice
```

### Ports
```
las ports ls                            # view port registry
las ports free [--start N] [--end N]    # get a free port number (default range 9000-9999)
las ports claim APP [--port N]          # atomically claim and register a port
las ports release PORT                  # release a registered port
las ports audit                         # cross-check registry against `lsof` — finds ghosts + unregistered listeners
```

### TTS Queue
```
las speak "Hello"                       # enqueue TTS (uses agent voice + name from .las-agent.json)
las queue ls                            # show pending items
las queue clear                         # clear all pending messages
```

### Other
```
las boarding                            # print path to the onboarding page
las boarding --open                     # open in browser
```

---

## Society rules

Agents share resources and follow a civility contract:

1. **Voice queue** — always via `POST /queue/speak` or `las speak`, never `say` directly; the queue prevents collisions
2. **Voice language** — each TTS voice has a fixed language; English voices speak English text, Spanish voices speak Spanish text — never mix them
3. **Ports** — always reserved via `las ports claim` or `POST /ports/claim` before starting any server
4. **Voices** — unique per agent; declared in `.las-agent.json` with a `locale` field (e.g. `en-US`, `es-MX`)
5. **Messages** — sent via `las agent inject NAME "msg"` or `POST /agents/{name}/inject`, delivered over **vortexia** (a sibling MQTT broker, see `vortexia/PROTOCOL.md`) rather than terminal injection. Not retained — the recipient only receives it if their `/las-agent` skill happens to be polling their vortexia inbox at that moment (it does so once, at the start of each session, via `las agent poll`). No live terminal, no on-disk queue; retry or wait for them to start a session.
6. **Response language** — agents respond in the language of their TTS voice (`locale` field in `.las-agent.json`)

---

## Backend API

Runs at `http://localhost:8700` · Docs at `http://localhost:8700/docs`

Endpoints below are cross-checked against `app.openapi()['paths']` in `backend/main.py` — this table lists exactly what's live, nothing aspirational.

| Endpoint | Description |
|---|---|
| `GET /health` | Backend liveness check |
| `GET /agents` | All registered agents |
| `POST /agents` | Register / update an agent |
| `DELETE /agents/{name}` | Unregister an agent |
| `PATCH /agents/{name}` | Rename an agent (`{new_name, pronunciation?}`) |
| `POST /agents/{name}/focus` | Bring the agent's iTerm2 window to the front |
| `POST /agents/{name}/terminal` | Open a new iTerm2 window running `claude` in the agent's directory |
| `GET /agents/{name}/ttys` | List TTYs known to be associated with the agent |
| `POST /agents/{name}/inject` | Publish a message to the agent's vortexia inbox (`las/agent/{name}/inbox`) |
| `POST /agents/{name}/vortexia/register` | Publish a retained "online" presence payload for the agent on vortexia |
| `GET /agents/{name}/vortexia/poll` | Drain the agent's vortexia inbox for up to `timeout` seconds and return what arrived |
| `POST /agents/{name}/mute` | Mute agent TTS |
| `DELETE /agents/{name}/mute` | Unmute agent TTS |
| `GET /agents/{name}/muted` | Check whether an agent is muted |
| `POST /agents/{name}/pin-tty` | Store a TTY linked via `las link` for the widget to pick up |
| `GET /agents/{name}/pending-link` | Return and clear the pending linked TTY (consumed once) |
| `GET /widget/{name}` | HTML page rendering the floating widget for an agent |
| `GET /debug/iterm_ttys` | List all TTYs currently known to iTerm2 via AppleScript |
| `GET /voices` | All voices with `{name, lang, flag}` |
| `GET /voices/{name}` | Language info for one voice |
| `GET /voices/random` | Random unused voice name |
| `GET /ports` | Port registry |
| `POST /ports` | Register a port directly (no availability check) |
| `DELETE /ports/{port}` | Release a port |
| `GET /ports/free` | Get a free port number (`?start=&end=`, default 9000-9999) |
| `POST /ports/claim` | Atomically claim + register a port |
| `POST /queue/speak` | Enqueue TTS `{text, voice, name}` |
| `GET /queue` | Current queue |
| `DELETE /queue` | Clear queue |
| `POST /attribution` | Record a file attribution entry |
| `GET /attribution` | File attribution log (`?file=` or `?name=`) |

Interactive docs (Swagger UI) are always available live at `http://localhost:8700/docs`.

A TypeScript SDK is available at `sdk/society.ts`.

---

## Widget buttons

Each widget (Electron, `widget-electron/`) has a name/log face with a door
button top-right, and a row of face buttons at the bottom:

| Button | Action |
|---|---|
| 🚪 Door (top-right, next to the name) | Deactivate: mark inactive, close this widget (session untouched) — see `las agent deactivate` |
| ⚙ Gear | Toggle settings mode inline (name/log stay visible above it; every other face button hides; gear shows "pressed" while open) |
| 🧹 Clear | Type `/clear` into the linked terminal(s) |
| `>_` Terminal | Toggle the command palette |
| 🔊 Speaker | Toggle mute |
| 🎙 Mic | Toggle dictation (click to start/stop; local Whisper transcription) |
| ⌦ Focus | Focus the linked terminal (right-click, or long-press, to link a new TTY) |

## Command palette

Click the terminal button (`>_`) to open the **command palette**. Each saved
command is either `openTerminal` (opens iTerm2 at a directory, optionally
running a shell command) or `sendMessage` (sends text to the agent's own
vortexia inbox — the dictation pipeline's send primitive). Edit or delete a
row inline; `+ Add command` creates a new one.

## Widget settings

Click the ⚙ gear button to open **settings** — inline, not a separate
screen; the widget's own name/log stay visible above it:

- **Color** / **Opacity** — the opacity slider only fades the fill of the
  background, name text, and face-button circles; each one's outline
  (the name's letter stroke, each button's border) stays crisp/opaque
  regardless, so the widget stays readable even very transparent.
- **Always on top**
- **Mute**
- **Expand when hidden** (on by default) — while occluded/off-Space, the
  widget balloons to a big, click-through, full-screen name banner instead
  of just disappearing; shrinks back `RESTORE_DELAY_MS` (2s by default,
  `widget-electron/renderer/widget.js`) after becoming visible again.
  When several widgets share the same macOS Space, they tile that Space's
  screen as a mosaic (halves for 2, one of five layouts for 3, a 2-column
  grid for 4+) instead of overlapping — grouped per `(display, Space)`, not
  just per physical display, so unrelated agents on other Spaces are never
  pulled into the same grid.
- **Wake up via vortexia** — lets `las agent focus` wake this agent from
  inactive (see the CLI table above) instead of reporting "not found".
- **Dictation language**

The agent's name auto-fits its box: it shrinks to the widest size that still
fits on one line, and if it still doesn't fit, breaks at whichever generic
title boundary (a space, a hyphen, or a lowercase→Uppercase transition)
falls closest to the middle — same rule in both the compact face and the
expanded/mosaic banner, just with a much bigger target size in the latter.

---

## Skills (Claude Code)

| Skill | What it does |
|---|---|
| `/local-agent-voice` | Change the agent's TTS voice (updates locale too) |
| `/local-agent-pronunciation` | Set a phonetic hint for TTS |
| `/local-agent-widget` | Reopen the floating widget |

---

## Project layout

```
backend/        FastAPI backend (port 8700)
cli/            `las` CLI (Click)
docs/           boarding.html — full onboarding reference
sdk/            TypeScript client
skills/         Claude Code skills
tests/          Test suite (pytest)
widget-electron/  Cross-platform floating widget (Electron)
```

---

## License

MIT
