---
name: local-agent-voice
description: Change the TTS voice of the local agent in the current directory.
allowed-tools: Bash(las:*) Bash(python3:*)
---

# /local-agent-voice — Change Agent Voice

Every agent speaks through Kokoro. Its voice is a Kokoro id in `.las-agent.json`
(`tts_voice`, e.g. `em_alex+am_onyx`); its language is `locale`.

## Parameters
- `$1` — (optional) Kokoro voice id. If omitted, picks a free one of the agent's language.

## Steps

### 1. Read the current agent
```bash
python3 -c "import json; d=json.load(open('.las-agent.json')); print(d.get('name'), d.get('locale'), d.get('tts_voice'))"
```
No file → this directory has no agent (`las agent new NAME` first).

### 2. Choose the voice
- `$1` given: check it exists with `las voices info $1` (an error means unknown — show `las voices list --lang <es|en>`).
- Otherwise: `las voices random --locale LOCALE` (add `--gender female|male` if the user asked for one).
- The voice must be in the agent's language: Spanish ids start `ef_`/`em_`, English `af_`/`am_`/`bf_`/`bm_`.

### 3. Write it and reload
```bash
python3 -c "
import json; p='.las-agent.json'; d=json.load(open(p)); d['tts_voice']='VOICE'
open(p,'w').write(json.dumps(d,indent=2,ensure_ascii=False)+'\n')"
las agent sync && las widget
```

### 4. Hear it and confirm
`las speak "<a short line in the agent's language>" --name AGENT`, then tell the user: old voice → new voice.
