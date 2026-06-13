---
name: new-local-agent
description: Register a new agent in the current directory. Creates .agent.json, registers with the backend, launches the sticky widget, and assigns a voice.
allowed-tools: Bash(curl:*) Bash(python3:*)
---

# /new-local-agent — Register a New Local Agent

Creates a named agent in the **current working directory**.

## Parameters
- `$1` — Agent name (required). e.g. `System`, `Garantido`, `Vacaciones`

## Execution steps

### 1. Parse inputs
- AGENT = first argument (required)

### 2. Ensure system is running
```bash
PATH="$HOME/.local/bin:$PATH" las status
```
If this fails (backend not running), start it:
```bash
PATH="$HOME/.local/bin:$PATH" las start && sleep 2
```

### 3. Get unique voice and its language
```bash
curl -s http://localhost:8700/voices/random
```
Save VOICE name. Then look up its language:
```bash
curl -s http://localhost:8700/voices/VOICE
```
Save LANG (e.g. `en-US`). If 404, default to `en-US`.

### 4. Write .agent.json in CWD
```bash
python3 -c "
import json, datetime
data = {
  'name': 'AGENT',
  'voice': 'VOICE',
  'locale': 'LANG',
  'pronunciation': 'AGENT',
  'backend_url': 'http://localhost:8700',
  'frontend_url': 'http://localhost:8700/widget/AGENT',
  'created': str(datetime.date.today())
}
open('.agent.json','w').write(json.dumps(data,indent=2,ensure_ascii=False))
"
```

### 5. Register with backend
```bash
curl -s -X POST http://localhost:8700/agents \
  -H "Content-Type: application/json" \
  -d '{"name":"AGENT","voice":"VOICE","path":"CWD","backend_url":"http://localhost:8700","frontend_url":"http://localhost:8700/widget/AGENT"}'
```

### 6. Create session channels
```bash
mkdir -p CWD/session
touch CWD/session/bitacora.md CWD/session/extern-inbox.md
```

### 7. Register ports (MANDATORY)

Before the agent can start any HTTP server, it must register its ports.

Get a free port for each server this agent will run:
```bash
curl -s http://localhost:8700/ports/free
```

Register each port before use:
```bash
curl -s -X POST http://localhost:8700/ports/claim \
  -H "Content-Type: application/json" \
  -d '{"port": PORT, "app": "APP_DESCRIPTION", "local_agent": "AGENT", "path": "CWD"}'
```

**Show the agent its registered ports and write them into any start scripts or config files (package.json, .env, etc.).**

Remind the agent of the port contract:
- **Never hardcode a port** that isn't in the registry.
- **Always check `/ports` before starting a server** — if occupied by another agent, notify them via their `session/extern-inbox.md` and wait.
- Using another agent's port crashes widgets and audio across the entire Society.

### 8. Launch widget
```bash
PATH="$HOME/.local/bin:$PATH" las widget AGENT
```

### 9. Verify consistency
```bash
python3 /Users/josetabuyo/Development/local-agent-society/tests/test_agent_consistency.py
```
If this fails, report the errors to the user before continuing.

### 10. Announce
```bash
PATH="$HOME/.local/bin:$PATH" las speak "Hello! I am AGENT, ready." --name AGENT
```

### 11. Report
Confirm: name, voice, locale, .agent.json created, ports registered, widget launched.
