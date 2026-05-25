---
name: local-agent-society
description: Multi-agent society for Claude Code. Each project folder gets a named family of agents (Haiku worker + Sonnet protagonist + Opus advisor) that communicate via session files, share a port registry, and announce via macOS TTS.
version: 1.0.0
author: josetabuyo
requires: macOS, Swift 5.6+, Python 3.8+, Claude Code CLI
---

# Local Agent Society

A system that turns Claude Code sessions into a coordinated society of agents.

## Concepts

- **Family** — a named group of agents tied to a project directory (e.g. `System`, `Garantido`)
- **Sonnet** — the protagonist. Talks to you, delegates to Haiku, consults Opus
- **Haiku** — the worker. Handles heavy file ops, MCP calls, repetitive tasks. Silent.
- **Opus** — the advisor. Consulted for important decisions. Silent.
- **Voice** — each family has one unique TTS voice (Sonnet speaks, others don't)
- **Widget** — always-on-top green sticky showing the family name per desktop

## Install

```bash
git clone https://github.com/josetabuyo/local-agent-society
cd local-agent-society
./install.sh
```

## Usage

Open Claude in any project folder:
```
/new-local-agent MyProject
```

That's it. The system handles the rest.

## Skills

| Skill | Description |
|-------|-------------|
| `/new-local-agent <Name> [Members]` | Baptize a new agent family |
| `/local-agent-voice [VoiceName]` | Change the family's TTS voice |
| `/local-agent-pronunciation <text>` | Set phonetic hint for TTS |

## API

Backend runs at `http://localhost:8700`

| Endpoint | Description |
|----------|-------------|
| `GET /agents` | List all registered families |
| `GET /ports` | Port registry |
| `GET /ports/free` | Get a free port |
| `POST /queue/speak` | Enqueue TTS message |
| `POST /attribution` | Record file attribution |
| `GET /attribution?file=...` | Who wrote what |
| `GET /docs` | Interactive API docs |
