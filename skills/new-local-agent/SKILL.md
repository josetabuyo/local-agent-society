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

### 3. Get unique voice
```bash
curl -s http://localhost:8700/voices/random
```

### 4. Write .agent.json in CWD
```bash
python3 -c "
import json, datetime
data = {
  'name': 'AGENT',
  'voice': 'VOICE',
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

### 6. Launch widget
```bash
PATH="$HOME/.local/bin:$PATH" las widget AGENT
```

### 7. Create session channels
```bash
mkdir -p CWD/session
touch CWD/session/bitacora.md
```

### 8. Verify consistency
```bash
python3 INSTALL_DIR/tests/test_agent_consistency.py
```
If this fails, report the errors to the user before continuing.

### 9. Announce
```bash
PATH="$HOME/.local/bin:$PATH" las speak "Here! AGENT" --name AGENT
```

### 10. Report
Confirm: name, voice, .agent.json created, widget launched.
