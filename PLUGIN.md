---
name: local-agent-society
description: Multi-agent society for Claude Code. Each project folder gets a named family of agents that communicate via Claude's native Agent tool, share a port registry, and announce via macOS TTS.
version: 2.0.0
author: josetabuyo
requires: macOS, Swift 5.6+, Python 3.8+, Claude Code CLI
---

# Local Agent Society

A system that turns Claude Code sessions into a coordinated society of agents.

## Concepts

- **Family** — a named group of agents tied to a project directory (e.g. `System`, `Garantido`)
- **Sonnet** — the protagonist. Talks to you. Delegates via the Agent tool.
- **Haiku** — spawned on demand for low-cost tasks: file searches, MCP calls, summaries, repetitive work
- **Opus** — spawned on demand for high-complexity tasks: architecture, deep debugging, long reasoning
- **Voice** — each family has one unique TTS voice (Sonnet speaks, subagents don't)
- **Widget** — always-on-top green sticky showing the family name per desktop

## Model selection

| Difficulty | Model | Use cases |
|-----------|-------|-----------|
| Low | Haiku-4.5 | Formatting, renaming, lookups, MCP calls, rapid summaries |
| Medium | Sonnet-4.6 | Most coding tasks, creative writing, deep analysis |
| High | Opus-4.7 | Complex architecture, heavy debugging, long reasoning |

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
