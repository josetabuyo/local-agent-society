---
name: new-local-agent
description: Baptize a new agent family in the current directory. Creates .agent.json, registers with the backend, launches the sticky widget, and assigns a voice.
allowed-tools: Bash(curl:*) Bash(python3:*)
---

# /new-local-agent — Baptize a Local Agent Family

Creates a named agent family in the **current working directory**.

## Parameters
- `$1` — Family name (required). e.g. `System`, `Garantido`, `Vacaciones`

## Execution steps

### 1. Parse inputs
- FAMILY = first argument (required)

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
Tell the running `Local Agent Society.app` to open a widget for this family via URL scheme:
```bash
open "localagentsociety://FAMILY"
```
If `start.sh` was called in step 2, the tray app is already running. The URL scheme triggers `openWidget(for:)` which spawns a full `WidgetWindow` with the ··· config button (color, opacity, always-on-top).

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
Confirm: family, voice, .agent.json created, widget launched.
