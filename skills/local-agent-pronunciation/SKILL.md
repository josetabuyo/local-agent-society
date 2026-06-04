---
name: local-agent-pronunciation
description: Set the pronunciation hint for the local agent's TTS voice.
allowed-tools: Bash(python3:*) Bash(say:*)
---

# /local-agent-pronunciation — Set Agent Pronunciation

The pronunciation field stores a phonetic hint used by TTS when speaking the agent's name.
Example: agent `Garantido` → pronunciation `Ga-ran-ti-do` (slowed spelling helps some voices).

## Parameters
- `$1` — Pronunciation text (required). Phonetic hint for the TTS engine.

## Steps

### 1. Read .agent.json
```bash
python3 -c "import json; d=json.load(open('.agent.json')); print(d.get('name'), d.get('voice','Samantha'), d.get('pronunciation',''))"
```
If file does not exist: tell user no agent is baptized here.

### 2. Update pronunciation field
```bash
python3 -c "
import json
d = json.load(open('.agent.json'))
d['pronunciation'] = 'PRONUNCIATION_TEXT'
open('.agent.json','w').write(json.dumps(d,indent=2,ensure_ascii=False))
print('Updated')
"
```

### 3. Test it aloud
```bash
say -v "VOICE" "PRONUNCIATION_TEXT"
```

### 4. Confirm to user
Show old pronunciation → new pronunciation and confirm it was spoken.
