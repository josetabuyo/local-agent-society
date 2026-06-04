---
name: new-local-agent
description: Register a new agent in the current directory. Creates .agent.json, registers with the backend, launches the sticky widget, and assigns a voice.
allowed-tools: Bash(curl:*) Bash(python3:*) Bash(open:*)
---

# /new-local-agent — Baptize a Local Agent Family

Creates a named agent in the **current working directory**.

## Parameters
- `$1` — Family name (required). e.g. `System`, `Garantido`, `Vacaciones`

## Execution steps

### 1. Parse inputs
- FAMILY = first argument (required)

### 2. Ensure system is running
```bash
curl -s http://localhost:8700/health
```
If this fails, start it:
```bash
bash INSTALL_DIR/start.sh && sleep 2
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
  'name': 'FAMILY',
  'voice': 'VOICE',
  'pronunciation': 'FAMILY',
  'backend_url': 'http://localhost:8700',
  'frontend_url': 'http://localhost:8700/widget/FAMILY',
  'created': str(datetime.date.today())
}
open('.agent.json','w').write(json.dumps(data,indent=2,ensure_ascii=False))
"
```

### 5. Register with backend
```bash
curl -s -X POST http://localhost:8700/agents \
  -H "Content-Type: application/json" \
  -d '{"name":"FAMILY","voice":"VOICE","path":"CWD","backend_url":"http://localhost:8700","frontend_url":"http://localhost:8700/widget/FAMILY"}'
```

### 6. Launch widget
```bash
open "localagentsociety://FAMILY"
```

### 7. Create session channels
SLUG = FAMILY lowercased.

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
curl -s -X POST http://localhost:8700/queue/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"Here! FAMILY","voice":"VOICE","name":"FAMILY"}'
```

### 10. Report
Confirm: name, voice, .agent.json created, widget launched.
