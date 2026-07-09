---
name: local-agent-society
description: Multi-agent society for Claude Code. Each project folder gets a named agent that shares a port registry, communicates via live terminal injection, and announces via macOS TTS.
version: 2.0.0
author: josetabuyo
requires: macOS, Swift 5.6+, Python 3.10+, Claude Code CLI
---

# Local Agent Society

A system that turns Claude Code sessions into a coordinated society of agents.

## Concepts

- **Agent** — a named identity tied to a project directory (e.g. `System`, `Garantido`), declared in that directory's `.agent.json`
- **Voice** — each agent has one unique TTS voice with a fixed language
- **Widget** — an always-on-top floating tray window showing the agent name on every Space
- **Inject** — live delivery of a message into another agent's terminal via `las agent inject` or `POST /agents/{name}/inject`; there are no inbox files and no polling

## Install

```bash
git clone https://github.com/josetabuyo/local-agent-society
cd local-agent-society
./install.sh
```

`./uninstall.sh` removes the system; `./update.sh` pulls latest and reinstalls. These are also reachable as `las install` / `las uninstall` / `las update`.

## Usage

Open Claude in any project folder:
```
/new-local-agent MyProject
```

That's it. The system handles the rest: it writes `.agent.json`, registers the agent with the backend, assigns a voice, and opens the widget.

Once registered, key day-to-day commands are `las agent inject NAME "msg"` (talk to another agent's terminal), `las widget [NAME]` (reopen a widget), and `las ports claim APP` (safely grab a port before starting a server).

## Skills

| Skill | Description |
|-------|-------------|
| `/new-local-agent <Name>` | Register a new agent |
| `/local-agent-voice [VoiceName]` | Change the agent's TTS voice |
| `/local-agent-pronunciation <text>` | Set phonetic hint for TTS |
| `/local-agent-widget` | Reopen the floating widget |

## API

Backend runs at `http://localhost:8700`. Full endpoint list is in `README.md`; the ones most relevant to agent-to-agent coordination:

| Endpoint | Description |
|----------|-------------|
| `GET /agents` | List all registered agents |
| `POST /agents/{name}/inject` | Inject a message into a live agent terminal |
| `GET /ports` | Port registry |
| `GET /ports/free` | Get a free port |
| `POST /ports/claim` | Atomically claim + register a port |
| `POST /queue/speak` | Enqueue a TTS message |
| `POST /attribution` | Record file attribution |
| `GET /attribution?file=...` | Who wrote what |
| `GET /docs` | Interactive API docs (Swagger UI) |
