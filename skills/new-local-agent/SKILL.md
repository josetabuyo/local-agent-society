---
name: new-local-agent
description: Baptize a new agent family in the current directory. Creates .agent.json, registers with the backend, launches the sticky widget, and assigns a voice.
allowed-tools: Bash(curl:*) Bash(python3:*)
---

# /new-local-agent — Baptize a Local Agent Family

Creates a named agent family in the **current working directory**.

## Parameters
- `$1` — Family name (required). e.g. `System`, `Garantido`, `Vacaciones`
- `$2` — Members (optional). Format: `Model1-Model2`. Default: `Haiku-Sonnet-Opus`

## Role assignment

| Members           | Worker (subagent) | User-facing | Advisor (subagent) |
|-------------------|-------------------|-------------|---------------------|
| Haiku+Sonnet+Opus | Haiku             | Sonnet      | Opus                |
| Haiku+Sonnet      | Haiku             | Sonnet      | Sonnet              |
| Sonnet+Opus       | Sonnet            | Sonnet      | Opus                |
| Single model      | same              | same        | same                |

## Execution steps

### 1. Parse inputs
- FAMILY = first argument (required)
- Members from second arg, lowercase, split by `-`. Default: `["haiku","sonnet","opus"]`
- MEMBERS_STR = joined with ` · ` uppercase for display

### 2. Ensure system is running
```bash
curl -s http://localhost:8700/health
```
If this fails, start everything silently:
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
  'agent-family': 'FAMILY',
  'role': 'sonnet',
  'voice': 'VOICE',
  'pronunciation': 'FAMILY',
  'backend_url': 'http://localhost:8700',
  'frontend_url': 'http://localhost:8700/widget/FAMILY',
  'members': MEMBERS_LIST,
  'created': str(datetime.date.today())
}
open('.agent.json','w').write(json.dumps(data,indent=2,ensure_ascii=False))
"
```

### 5. Register with backend
```bash
curl -s -X POST http://localhost:8700/agents \
  -H "Content-Type: application/json" \
  -d '{"family":"FAMILY","role":"sonnet","voice":"VOICE","path":"CWD","backend_url":"http://localhost:8700","frontend_url":"http://localhost:8700/widget/FAMILY","members":MEMBERS_LIST}'
```

### 6. Launch widget
```bash
INSTALL_DIR/widget/widget FAMILY "MEMBERS_STR" &
```

### 7. Create session channels
SLUG = FAMILY lowercased.

```bash
mkdir -p CWD/session
touch CWD/session/SLUG-inbox.md    # inter-family messages
touch CWD/session/extern-inbox.md  # external injection channel
touch CWD/session/bitacora.md      # conversation log
```

### 9. Verify consistency
```bash
python3 INSTALL_DIR/tests/test_agent_consistency.py
```
If this fails, report the errors to the user before continuing.

### 10. Announce
```bash
curl -s -X POST http://localhost:8700/queue/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"Here! FAMILY","voice":"VOICE","family":"FAMILY"}'
```

### 11. Report
Confirm: family, voice, members, .agent.json created, widget launched.
Note: Haiku and Opus are spawned on demand via the Agent tool — no persistent processes needed.
