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

Open Claude Code in any project directory and run:

```
/new-local-agent
```

The skill registers the agent with the backend, assigns a unique voice (with its language), and opens the widget.

---

## The `las` CLI

### System
```
las status                              # backend status, agents, ports
las start / stop                        # start or stop the backend
las logs                                # tail backend log
```

### Agents
```
las agents                              # list all registered agents
las agent sync                          # sync .agent.json → backend
las agent restore [NAME]                # recover .agent.json from backend
las agent inject NAME "msg"             # send message to another agent's terminal
las agent inject NAME "msg" --from Me   # with sender label
las agent clean [NAME]                  # inject /clear into agent terminal
las agent mute [NAME]                   # silence an agent's TTS
las agent unmute [NAME]                 # re-enable TTS
las agent delete [NAME]                 # unregister from backend
las widget [NAME]                       # reopen the floating widget
```

### Voices
```
las voices list                         # all voices with language flag
las voices info Samantha                # language info for one voice
las voices random                       # pick a random unused voice
```

### Ports
```
las ports ls                            # view port registry
las ports free                          # get a free port number
las ports claim APP [--port N]          # atomically claim and register a port
las ports release PORT                  # release a registered port
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
5. **Messages** — sent via `las agent inject`, or written to `session/extern-inbox.md` for the next conversation
6. **Response language** — agents respond in the language of their TTS voice (`locale` field in `.agent.json`)

---

## Backend API

Runs at `http://localhost:8700` · Docs at `http://localhost:8700/docs`

| Endpoint | Description |
|---|---|
| `GET /agents` | All registered agents |
| `POST /agents` | Register / update an agent |
| `DELETE /agents/{name}` | Unregister an agent |
| `POST /agents/{name}/inject` | Inject into a live terminal |
| `POST /agents/{name}/mute` | Mute agent TTS |
| `DELETE /agents/{name}/mute` | Unmute agent TTS |
| `GET /voices` | All voices with `{name, lang, flag}` |
| `GET /voices/{name}` | Language info for one voice |
| `GET /voices/random` | Random unused voice name |
| `GET /ports` | Port registry |
| `GET /ports/free` | Get a free port number |
| `POST /ports/claim` | Atomically claim + register a port |
| `DELETE /ports/{port}` | Release a port |
| `POST /queue/speak` | Enqueue TTS `{text, voice, name}` |
| `GET /queue` | Current queue |
| `DELETE /queue` | Clear queue |
| `GET /attribution` | File attribution log |

A TypeScript SDK is available at `sdk/society.ts`.

---

## Widget config

Click the `⋯` button on any widget to open the settings popover:

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
| `/new-local-agent` | Register a new agent with voice + locale |
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
