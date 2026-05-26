#!/bin/bash
# Haiku worker — acepta un directorio de proyecto como $1
# Uso: bash haiku-watcher.sh /path/to/project
export PATH="/Users/josetabuyo/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
PROJECT_DIR="${1:-$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )")}"
SESSION_DIR="$PROJECT_DIR/session"
INBOX="$SESSION_DIR/haiku-inbox.md"
OUTBOX="$SESSION_DIR/haiku-outbox.md"
BACKEND="http://localhost:8700"
FAMILY=$(python3 -c "import json; d=json.load(open('$PROJECT_DIR/.agent.json')); print(d.get('agent-family','Unknown'))" 2>/dev/null || echo "Unknown")

mkdir -p "$SESSION_DIR"
echo "" > "$INBOX"
echo "[haiku-watcher] arrancando para $FAMILY en $PROJECT_DIR"

while true; do
    content=$(cat "$INBOX" 2>/dev/null)

    if [ -n "$content" ]; then
        > "$INBOX"
        timestamp=$(date '+%Y-%m-%d %H:%M:%S')

        # Agregar instrucción de attribution al prompt
        full_prompt="$content

---
Al finalizar, lista cada archivo que creaste o modificaste con el formato exacto:
MODIFIED: /ruta/absoluta/al/archivo"

        echo "" >> "$OUTBOX"
        echo "### [$timestamp] Haiku" >> "$OUTBOX"
        echo "" >> "$OUTBOX"

        response=$(echo "$full_prompt" | claude -p --model haiku \
            --permission-mode bypassPermissions \
            --add-dir "$PROJECT_DIR" 2>&1)

        echo "$response" >> "$OUTBOX"
        echo "" >> "$OUTBOX"
        echo "---" >> "$OUTBOX"

        # Attribution: parsear líneas MODIFIED:
        echo "$response" | grep "^MODIFIED:" | while read -r line; do
            filepath=$(echo "$line" | sed 's/^MODIFIED: //')
            curl -s -X POST "$BACKEND/attribution" \
                -H "Content-Type: application/json" \
                -d "{\"file\":\"$filepath\",\"agent\":\"haiku\",\"family\":\"$FAMILY\",\"timestamp\":\"$timestamp\",\"project\":\"$PROJECT_DIR\"}" \
                --max-time 2 > /dev/null 2>&1
        done

        # Flag + notificación macOS
        echo "$timestamp" > "$SESSION_DIR/haiku-done.flag"
        osascript -e "display notification \"Haiku terminó — $FAMILY\" with title \"Local Agent\" sound name \"Glass\"" 2>/dev/null

        echo "[haiku-watcher] respondido a las $timestamp"
    fi

    sleep 1
done
