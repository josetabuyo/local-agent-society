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

- macOS (arm64)
- Swift 5.6+
- Python 3.10+
- [Claude Code CLI](https://claude.ai/code)

---

## Install

```bash
git clone https://github.com/josetabuyo/local-agent-society
cd local-agent-society
./install.sh
```

This compiles the tray app, registers the LaunchAgent, starts the backend on port 8700, and installs the `las` CLI.

---

## Create your first agent

In any project directory, run:

```
las agent new MyProject
```

The command writes `.agent.json`, registers the agent with the backend, assigns a unique voice (with its language), and opens the widget.

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
las agent new NAME [--voice V] [--dir D]  # write .agent.json, register, launch widget
las agent sync                          # sync .agent.json → backend
las agent restore [NAME]                # recover .agent.json from backend
las agent rename [OLD] NEW [--pronunciation P]  # rename in backend + update .agent.json
las agent focus [NAME]                  # bring the agent's iTerm2 window to the front
las agent inject NAME "msg"             # send message to another agent's terminal
las agent inject NAME "msg" --from Me   # with sender label
las agent clean [NAME]                  # inject /clear into agent terminal
las agent mute [NAME]                   # silence an agent's TTS
las agent unmute [NAME]                 # re-enable TTS
las agent delete [NAME] [--yes]         # unregister from backend
las widget [NAME]                       # reopen one agent's floating widget
las widgets                             # reopen every registered agent's widget
las link [--agent NAME] [--tty PATH]    # link the current (or given) terminal to a widget
```
`NAME` is optional on most `agent` subcommands — it defaults to the agent registered for the current directory (via `.agent.json` or a path match in the backend registry).

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
las speak "Hello"                       # enqueue TTS (uses agent voice + name from .agent.json)
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
4. **Voices** — unique per agent; declared in `.agent.json` with a `locale` field (e.g. `en-US`, `es-MX`)
5. **Messages** — sent live via `las agent inject NAME "msg"` or `POST /agents/{name}/inject`; delivered straight into the target agent's TTY. There are no inbox files and no polling — if the agent has no live terminal the message isn't delivered (or is queued for delivery when it comes back live, depending on the backend response); retry or wait for them to start a session.
6. **Response language** — agents respond in the language of their TTS voice (`locale` field in `.agent.json`)

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
| `POST /agents/{name}/inject` | Inject a message into a live terminal (queues it if the agent isn't live and `queue` is set) |
| `GET /agents/{name}/pending` | List messages queued for delivery when the agent comes back live |
| `DELETE /agents/{name}/pending` | Clear the pending-message queue for an agent |
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

Each widget has six buttons at the bottom:

| Button | Short press | Long press |
|---|---|---|
| ⚙ Gear | Toggle config panel (slides down) | — |
| 🧹 Clear | Inject `/clear` into linked terminal | — |
| `>_` Terminal | Toggle command panel (slides down) | — |
| 🔊 Speaker | Toggle mute | Volume + voice picker |
| 🎙 Mic | Toggle speech input | Language picker |
| ⊕ Scope | Focus linked terminal | Drag to link a new TTY |

## Command panel

Click the terminal button (`>_`) to slide open the **command panel** below the widget.

Each row shows a **grip handle** (drag to reorder), a **label** (clickable — executes the command), and a scrolling **marquee** with the exact command that will run.

Three command types:

| Type | What it does |
|---|---|
| **claude** | Opens iTerm2 running `claude --model <id>` in the agent's directory |
| **Terminal** | Opens iTerm2 as a plain shell in the agent's directory (no claude) |
| **Inject** | Types a command into the currently linked terminal session |

Click ✏ on any row to edit or delete it. Use `+ Add command` to create new ones. If you leave the alias blank, a clean alias is derived from the payload (e.g. `/clear` → `clear`).

## Widget config

Click the ⚙ gear button to slide open the **config panel** below the widget:

- **Color** — widget background color
- **Opacity** — transparency level
- **Always on top** — keep widget above other windows
- **Expand on space change** — auto-expand when switching Spaces; when multiple widgets share the same Space they tile the screen as a mosaic (halves for 2, random split for 3, 2×2 grid for 4+) instead of overlapping
- **Voice** — shows current voice name and language; **Test voice** button speaks in the correct language; **Change voice…** opens a picker

Long-press the mic button to change the speech recognition language (independent from TTS voice).

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
widget/         macOS tray app (Swift)
```

---

## License

MIT
