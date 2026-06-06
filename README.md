# Local Agent Society

A coordination layer that turns Claude Code sessions into a **society of named agents** — each living in its own project folder, with a unique voice, a floating widget, and shared infrastructure for ports, TTS, and inter-agent messaging.

Every agent knows the rules. They never talk over each other. They never steal ports. They sign their work.

---

## What it does

- **Named agents** — each project directory registers as a named agent (`Wavi`, `Garantido`, `NeuroFlow`…) with its own identity and voice
- **Floating widget** — a macOS tray app shows the agent name on every Space, always on top
- **Voice queue** — all TTS goes through a central queue so agents never collide when speaking
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

That's it. The skill registers the agent with the backend, assigns a unique voice, and opens the widget.

---

## The `las` CLI

```
las status                          # backend status, agents, ports
las start / stop                    # start or stop the backend
las speak "Hello"                   # enqueue TTS (voice queue)
las agents                          # list registered agents
las agent inject Wavi "Hey" --from Me   # send message to another agent's terminal
las agent clean                     # inject /clear into current agent
las ports                           # view port registry
las voices                          # available TTS voices
las boarding                        # print path to the onboarding page
las boarding --open                 # open in browser
```

---

## Society rules

Agents share resources and follow a civility contract:

1. **Voice** — always via `POST /queue/speak` or `las speak`, never `say` directly
2. **Ports** — always reserved via the registry before binding
3. **Voices** — unique per agent; declared in `.agent.json`
4. **Messages** — sent via `las agent inject`, not via files or shared state
5. **External channel** — scripts write to `session/extern-inbox.md` to reach an agent
6. **Language** — agents respond in the locale configured in `.agent.json`

Full reference: `las boarding`

---

## Backend API

Runs at `http://localhost:8700` · Docs at `http://localhost:8700/docs`

| Endpoint | Description |
|---|---|
| `GET /agents` | All registered agents |
| `POST /agents` | Register an agent |
| `GET /ports` | Port registry |
| `GET /ports/free` | Claim a free port |
| `POST /queue/speak` | Enqueue TTS |
| `POST /agents/{name}/inject` | Inject into a live terminal |
| `GET /attribution` | File attribution log |

A TypeScript SDK is available at `sdk/society.ts`.

---

## Skills (Claude Code)

| Skill | What it does |
|---|---|
| `/new-local-agent` | Register a new agent in the current directory |
| `/local-agent-voice` | Change the agent's TTS voice |
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
