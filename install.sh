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
echo "[ 1/7 ] Compiling widget..."
swiftc "$INSTALL_DIR/widget/widget.swift" -o "$INSTALL_DIR/widget/widget"

# ── 2. Python dependencies ────────────────────────────────────────────────────
echo "[ 2/7 ] Installing Python dependencies..."
pip3 install -q fastapi "uvicorn[standard]" --break-system-packages 2>/dev/null || \
pip3 install -q fastapi "uvicorn[standard]" 2>/dev/null

# ── 3. Install skills ─────────────────────────────────────────────────────────
echo "[ 3/7 ] Installing skills..."
for skill in new-local-agent local-agent-voice local-agent-pronunciation; do
    mkdir -p ~/.claude/skills/$skill
    sed "s|INSTALL_DIR|$INSTALL_DIR|g" \
        "$INSTALL_DIR/skills/$skill/SKILL.md" \
        > ~/.claude/skills/$skill/SKILL.md
    echo "         skill: $skill"
done

# ── 4. Install hook ───────────────────────────────────────────────────────────
echo "[ 4/7 ] Installing stop hook..."
mkdir -p ~/.claude/hooks
cp "$INSTALL_DIR/hooks/announce-here.sh" ~/.claude/hooks/announce-here.sh
chmod +x ~/.claude/hooks/announce-here.sh

# ── 5. Update ~/.claude/settings.json ────────────────────────────────────────
echo "[ 5/7 ] Updating Claude settings..."
SETTINGS=~/.claude/settings.json
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

# ── 6. Initialize runtime dirs and files ──────────────────────────────────────
echo "[ 6/7 ] Initializing runtime directories..."
mkdir -p "$INSTALL_DIR/backend/data" "$INSTALL_DIR/session"
for f in registry.json ports.json; do
    [ ! -f "$INSTALL_DIR/backend/data/$f" ] && echo '{}' > "$INSTALL_DIR/backend/data/$f"
done
[ ! -f "$INSTALL_DIR/backend/data/queue.json" ] && echo '[]' > "$INSTALL_DIR/backend/data/queue.json"
[ ! -f "$INSTALL_DIR/backend/data/attribution.json" ] && echo '[]' > "$INSTALL_DIR/backend/data/attribution.json"
touch "$INSTALL_DIR/session/haiku-inbox.md" "$INSTALL_DIR/session/haiku-outbox.md"
touch "$INSTALL_DIR/session/opus-inbox.md" "$INSTALL_DIR/session/opus-outbox.md"

# ── 7. launchd ────────────────────────────────────────────────────────────────
echo "[ 7/7 ] Registering launchd agent..."
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
        <string>$INSTALL_DIR/start.sh</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><false/>
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
  "agent-family": "$FAMILY",
  "role": "sonnet",
  "voice": "Samantha",
  "pronunciation": "$FAMILY",
  "backend_url": "http://localhost:8700",
  "frontend_url": "http://localhost:8700/widget/$FAMILY",
  "members": ["haiku", "sonnet", "opus"],
  "created": "$TODAY"
}
JSON
    echo "         .agent.json created (voice will randomize on first start)"
fi

echo ""
echo "Done! Start with:"
echo "  bash $INSTALL_DIR/start.sh"
