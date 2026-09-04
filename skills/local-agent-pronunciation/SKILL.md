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

### 1. Read the agent config
`.las-agent.json` is the current filename; `.agent.json` is read as a fallback for agents not yet migrated (see `scripts/migrate-agent-json.py`).
```bash
python3 -c "
import json, os
p = '.las-agent.json' if os.path.exists('.las-agent.json') else '.agent.json'
d = json.load(open(p))
print(d.get('name'), d.get('voice','Samantha'), d.get('pronunciation',''))
"
```
If neither file exists: tell user no agent is baptized here.

### 2. Update pronunciation field
Write back to whichever filename was read in step 1.
```bash
python3 -c "
import json, os
p = '.las-agent.json' if os.path.exists('.las-agent.json') else '.agent.json'
d = json.load(open(p))
d['pronunciation'] = 'PRONUNCIATION_TEXT'
open(p,'w').write(json.dumps(d,indent=2,ensure_ascii=False))
print('Updated')
"
```

### 3. Test it aloud
```bash
say -v "VOICE" "PRONUNCIATION_TEXT"
```

### 4. Confirm to user
Show old pronunciation → new pronunciation and confirm it was spoken.
