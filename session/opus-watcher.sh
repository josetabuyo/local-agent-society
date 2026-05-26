#!/bin/bash
# Opus advisor — acepta un directorio de proyecto como $1
# Uso: bash opus-watcher.sh /path/to/project
export PATH="/Users/josetabuyo/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
PROJECT_DIR="${1:-$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )")}"
SESSION_DIR="$PROJECT_DIR/session"
INBOX="$SESSION_DIR/opus-inbox.md"
OUTBOX="$SESSION_DIR/opus-outbox.md"
BACKEND="http://localhost:8700"
FAMILY=$(python3 -c "import json; d=json.load(open('$PROJECT_DIR/.agent.json')); print(d.get('agent-family','Unknown'))" 2>/dev/null || echo "Unknown")

mkdir -p "$SESSION_DIR"
echo "" > "$INBOX"
echo "[opus-watcher] arrancando para $FAMILY en $PROJECT_DIR"

while true; do
    content=$(cat "$INBOX" 2>/dev/null)

    if [ -n "$content" ]; then
        > "$INBOX"
        timestamp=$(date '+%Y-%m-%d %H:%M:%S')

        echo "" >> "$OUTBOX"
        echo "### [$timestamp] Opus" >> "$OUTBOX"
        echo "" >> "$OUTBOX"

        echo "$content" | claude -p --model opus \
            --permission-mode bypassPermissions \
            --add-dir "$PROJECT_DIR" \
            >> "$OUTBOX" 2>&1

        echo "" >> "$OUTBOX"
        echo "---" >> "$OUTBOX"

        echo "$timestamp" > "$SESSION_DIR/opus-done.flag"
        osascript -e "display notification \"Opus listo — $FAMILY\" with title \"Local Agent\" sound name \"Glass\"" 2>/dev/null

        echo "[opus-watcher] respondido a las $timestamp"
    fi

    sleep 1
done
