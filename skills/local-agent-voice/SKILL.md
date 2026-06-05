---
name: local-agent-voice
description: Change the TTS voice of the local agent in the current directory.
allowed-tools: Bash(curl:*) Bash(python3:*) Bash(say:*)
---

# /local-agent-voice — Change Agent Voice

## Parameters
- `$1` — (optional) Voice name. If omitted, assigns a new random voice.

## Steps

### 1. Read current .agent.json
```bash
python3 -c "import json; d=json.load(open('.agent.json')); print(d.get('name'), d.get('voice','Samantha'))"
```
If file does not exist, tell the user this directory has no agent (run `/new-local-agent` first).

### 2. Determine new voice
- If `$1` provided: use it as VOICE
- Otherwise: `curl -s http://localhost:8700/voices/random` and extract `voice`

### 3. Preview the voice
```bash
say -v "VOICE" "Here! AGENT"
```

### 4. Update .agent.json
```bash
python3 -c "
import json
d = json.load(open('.agent.json'))
d['voice'] = 'VOICE'
open('.agent.json','w').write(json.dumps(d,indent=2,ensure_ascii=False))
print('Updated')
"
```

### 5. Update backend registry
Re-register with same data but new voice via `POST /agents`:
```bash
curl -s -X POST http://localhost:8700/agents \
  -H "Content-Type: application/json" \
  -d '{"name":"AGENT","voice":"VOICE","path":"CWD","backend_url":"http://localhost:8700","frontend_url":"http://localhost:8700/widget/AGENT"}'
```

### 6. Confirm to user
Show: agent name, old voice → new voice.
