#!/bin/bash
# Local Agent Society — installer
# Usage: ./install.sh [FamilyName]
# Default family name: System
set -e

INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
FAMILY="${1:-System}"

echo "Local Agent Society — installing"
echo "  Directory : $INSTALL_DIR"
echo "  Family    : $FAMILY"
echo ""

# ── 1. Compile widget ─────────────────────────────────────────────────────────
echo "[ 1/5 ] Compiling widget..."
swiftc "$INSTALL_DIR/widget/widget.swift" -o "$INSTALL_DIR/widget/widget"

# ── 2. Python dependencies ────────────────────────────────────────────────────
echo "[ 2/5 ] Installing Python dependencies..."
VENV="$INSTALL_DIR/backend/.venv"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q fastapi "uvicorn[standard]"

# ── 3. Install skills ─────────────────────────────────────────────────────────
echo "[ 3/5 ] Installing skills..."
for skill in new-local-agent local-agent-voice local-agent-pronunciation local-agent-widget; do
    mkdir -p ~/.claude/skills/$skill
    sed "s|INSTALL_DIR|$INSTALL_DIR|g" \
        "$INSTALL_DIR/skills/$skill/SKILL.md" \
        > ~/.claude/skills/$skill/SKILL.md
    echo "         skill: $skill"
done

# ── 4. Install hook ───────────────────────────────────────────────────────────
echo "[ 4/5 ] Installing stop hook..."
mkdir -p ~/.claude/hooks
cp "$INSTALL_DIR/hooks/announce-here.sh" ~/.claude/hooks/announce-here.sh
chmod +x ~/.claude/hooks/announce-here.sh

# ── 5. Update ~/.claude/settings.json ────────────────────────────────────────
echo "[ 5/5 ] Updating Claude settings..."
python3 - <<PYEOF
import json, os

path = os.path.expanduser("~/.claude/settings.json")
with open(path) as f:
    s = json.load(f)

# permissions
perms = s.setdefault("permissions", {}).setdefault("allow", [])
for p in ["Bash(curl:*)", "Bash(python3:*)", "Bash(nohup:*)"]:
    if p not in perms:
        perms.append(p)

# stop hook
hooks = s.setdefault("hooks", {})
stop = hooks.setdefault("Stop", [])
hook_cmd = "bash $HOME/.claude/hooks/announce-here.sh"
already = any(
    h.get("command") == hook_cmd
    for entry in stop
    for h in entry.get("hooks", [])
)
if not already:
    stop.append({"matcher": "", "hooks": [{"type": "command", "command": hook_cmd}]})

with open(path, "w") as f:
    json.dump(s, f, indent=2)
print("         settings.json updated")
PYEOF

# ── Initialize session channels ───────────────────────────────────────────────
SLUG=$(echo "$FAMILY" | tr '[:upper:]' '[:lower:]')
touch "$INSTALL_DIR/session/${SLUG}-inbox.md"   # inter-family messages
touch "$INSTALL_DIR/session/extern-inbox.md"    # external injection channel
touch "$INSTALL_DIR/session/bitacora.md"        # conversation log

# ── Initialize backend data ───────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR/backend/data"
for f in registry.json ports.json; do
    [ ! -f "$INSTALL_DIR/backend/data/$f" ] && echo '{}' > "$INSTALL_DIR/backend/data/$f"
done
[ ! -f "$INSTALL_DIR/backend/data/queue.json" ] && echo '[]' > "$INSTALL_DIR/backend/data/queue.json"
[ ! -f "$INSTALL_DIR/backend/data/attribution.json" ] && echo '[]' > "$INSTALL_DIR/backend/data/attribution.json"

# ── Register launchd agent (backend) ─────────────────────────────────────────
PLIST=~/Library/LaunchAgents/com.localagent.system.plist
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.localagent.system</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$INSTALL_DIR/backend/serve.sh</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$INSTALL_DIR/backend/launchd.log</string>
    <key>StandardErrorPath</key><string>$INSTALL_DIR/backend/launchd.log</string>
</dict>
</plist>
PLIST
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

# ── Create .agent.json if not present ────────────────────────────────────────
if [ ! -f "$INSTALL_DIR/.agent.json" ]; then
    TODAY=$(date '+%Y-%m-%d')
    cat > "$INSTALL_DIR/.agent.json" <<JSON
{
  "name": "$FAMILY",
  "voice": "Samantha",
  "pronunciation": "$FAMILY",
  "backend_url": "http://localhost:8700",
  "frontend_url": "http://localhost:8700/widget/$FAMILY",
  "created": "$TODAY"
}
JSON
fi

echo ""
echo "Done! Start with:"
echo "  bash $INSTALL_DIR/start.sh"
