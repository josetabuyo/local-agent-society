#!/bin/bash
# Fired by Claude Code Stop hook.
# Enqueues "Here! <Family>" TTS if current dir has .agent.json

INPUT=$(cat)
CWD=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null)
[ -z "$CWD" ] && CWD="$PWD"

AGENT_FILE="$CWD/.agent.json"
[ ! -f "$AGENT_FILE" ] && exit 0

FAMILY=$(python3 -c "import json; d=json.load(open('$AGENT_FILE')); print(d.get('name',''))" 2>/dev/null)
VOICE=$(python3 -c "import json; d=json.load(open('$AGENT_FILE')); print(d.get('voice','Samantha'))" 2>/dev/null)

[ -z "$FAMILY" ] && exit 0

curl -s -X POST http://localhost:8700/queue/speak \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"Here! $FAMILY\", \"voice\": \"$VOICE\", \"name\": \"$FAMILY\"}" \
  --max-time 2 > /dev/null 2>&1

exit 0
