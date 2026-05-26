---
name: new-local-agent
description: Baptize a new agent family in the current directory. Creates .agent.json, registers with the backend, launches the sticky widget, assigns a voice, and starts Haiku/Opus watchers.
allowed-tools: Bash(curl:*) Bash(python3:*) Bash(say:*) Bash(nohup:*)
---

# /new-local-agent — Baptize a Local Agent Family

Creates a named agent family in the **current working directory**.

## Parameters
- `$1` — Family name (required). e.g. `System`, `Garantido`, `Vacaciones`
- `$2` — Members (optional). Format: `Model1-Model2`. Default: `Haiku-Sonnet-Opus`

## Role assignment

| Members           | Worker | User-facing | Advisor |
|-------------------|--------|-------------|---------|
| Haiku+Sonnet+Opus | Haiku  | Sonnet      | Opus    |
| Haiku+Sonnet      | Haiku  | Sonnet      | Sonnet  |
| Sonnet+Opus       | Sonnet | Sonnet      | Opus    |
| Single model      | same   | same        | same    |

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

### 7. Launch Haiku/Opus watchers as persistent launchd services

Create session files and launchd plists so watchers survive reboots and session closes.
SLUG = FAMILY lowercased.

```bash
mkdir -p CWD/session
touch CWD/session/haiku-inbox.md CWD/session/haiku-outbox.md
touch CWD/session/opus-inbox.md  CWD/session/opus-outbox.md
```

For each ROLE in [haiku, opus], write `~/Library/LaunchAgents/com.localagent.SLUG.ROLE.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.localagent.SLUG.ROLE</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>INSTALL_DIR/session/ROLE-watcher.sh</string>
        <string>CWD</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>CWD/session/ROLE-watcher.log</string>
    <key>StandardErrorPath</key><string>CWD/session/ROLE-watcher.log</string>
</dict>
</plist>
```

Then load each:
```bash
launchctl unload ~/Library/LaunchAgents/com.localagent.SLUG.ROLE.plist 2>/dev/null || true
launchctl load   ~/Library/LaunchAgents/com.localagent.SLUG.ROLE.plist
```

### 7b. Verify consistency
```bash
python3 INSTALL_DIR/tests/test_agent_consistency.py
```
If this fails, report the errors to the user before continuing.

### 8. Announce
```bash
curl -s -X POST http://localhost:8700/queue/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"Here! FAMILY","voice":"VOICE","family":"FAMILY"}'
```

### 9. Report
Confirm: family, voice, members, .agent.json created, widget launched, watchers running.
