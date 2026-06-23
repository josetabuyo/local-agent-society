#!/bin/bash
# Local Agent Society — installer
# Usage: ./install.sh [AgentName]
# Default agent name: System
set -e

INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
FAMILY="${1:-System}"

echo "Local Agent Society — installing"
echo "  Directory : $INSTALL_DIR"
echo "  Agent     : $FAMILY"
echo ""

# ── 1. Compile tray app bundle ────────────────────────────────────────────────
echo "[ 1/5 ] Compiling tray app..."
APP="$INSTALL_DIR/widget/Local Agent Society.app"
mkdir -p "$APP/Contents/MacOS"
swiftc "$INSTALL_DIR/widget/tray.swift" \
    -framework AppKit -framework Foundation -framework Speech -framework AVFoundation \
    -target arm64-apple-macos12 \
    -o "$APP/Contents/MacOS/tray"
codesign --force --deep --sign - "$APP"
# Only reset TCC permissions on first install (no existing binary).
# Re-running install.sh to update code must NOT break granted permissions.
if [ ! -f "$APP/Contents/Info.plist" ]; then
    tccutil reset Microphone com.localagentsociety.tray 2>/dev/null || true
    tccutil reset SpeechRecognition com.localagentsociety.tray 2>/dev/null || true
fi
cat > "$APP/Contents/Info.plist" <<INFOPLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>com.localagentsociety.tray</string>
    <key>CFBundleName</key><string>Local Agent Society</string>
    <key>CFBundleDisplayName</key><string>Local Agent Society</string>
    <key>CFBundleExecutable</key><string>tray</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1.1</string>
    <key>CFBundleShortVersionString</key><string>1.1</string>
    <key>NSPrincipalClass</key><string>NSApplication</string>
    <key>NSMicrophoneUsageDescription</key><string>Voice input for local agent session injection</string>
    <key>NSSpeechRecognitionUsageDescription</key><string>Transcribe voice notes to inject into the local agent session</string>
    <key>CFBundleURLTypes</key>
    <array>
        <dict>
            <key>CFBundleURLSchemes</key><array><string>localagentsociety</string></array>
            <key>CFBundleURLName</key><string>com.localagentsociety.open</string>
        </dict>
    </array>
</dict>
</plist>
INFOPLIST

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
touch "$INSTALL_DIR/session/${SLUG}-inbox.md"   # inter-agent messages
touch "$INSTALL_DIR/session/extern-inbox.md"    # external injection channel
touch "$INSTALL_DIR/session/bitacora.md"        # conversation log

# ── Initialize backend data ───────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR/backend/data"
for f in registry.json ports.json; do
    [ ! -f "$INSTALL_DIR/backend/data/$f" ] && echo '{}' > "$INSTALL_DIR/backend/data/$f"
done
[ ! -f "$INSTALL_DIR/backend/data/queue.json" ] && echo '[]' > "$INSTALL_DIR/backend/data/queue.json"
[ ! -f "$INSTALL_DIR/backend/data/attribution.json" ] && echo '[]' > "$INSTALL_DIR/backend/data/attribution.json"

# ── Purge legacy per-project watcher plists (haiku / opus) ───────────────────
# These were generated by an old multi-model system (pre-TTY-injection era).
# The scripts they referenced no longer exist; remove any survivors.
echo "[ +0 ] Purging legacy watcher plists..."
LEGACY=$(ls ~/Library/LaunchAgents/*.haiku.plist ~/Library/LaunchAgents/*.opus.plist 2>/dev/null || true)
if [ -n "$LEGACY" ]; then
    for plist in $LEGACY; do
        launchctl unload "$plist" 2>/dev/null || true
        rm -f "$plist"
        echo "         removed $(basename "$plist")"
    done
else
    echo "         none found"
fi

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

# ── Install `las` CLI ─────────────────────────────────────────────────────────
echo "[ +1 ] Installing las CLI..."
if command -v pipx &>/dev/null; then
    pipx install -e "$INSTALL_DIR" --force -q
    # Ensure ~/.local/bin is in PATH for future shells
    pipx ensurepath --force -q 2>/dev/null || true
    echo "         las → installed via pipx"
else
    pip3 install -e "$INSTALL_DIR" -q --break-system-packages 2>/dev/null \
        || pip3 install -e "$INSTALL_DIR" -q
    echo "         las → installed via pip"
fi

# ── Verify `las` is reachable — symlink into a PATH dir only if needed ────────
# pip+Homebrew installs directly to /opt/homebrew/bin; pipx installs to ~/.local/bin.
# Only create a symlink when las lives outside the standard PATH directories.
LAS_BIN="$HOME/.local/bin/las"
if [ -f "$LAS_BIN" ]; then
    for TARGET_DIR in /opt/homebrew/bin /usr/local/bin; do
        DEST="$TARGET_DIR/las"
        if [ -d "$TARGET_DIR" ] && [ -w "$TARGET_DIR" ] && [ "$LAS_BIN" != "$DEST" ]; then
            ln -sf "$LAS_BIN" "$DEST" 2>/dev/null \
                && echo "         las → symlinked to $DEST" \
                && break
        fi
    done
fi

# Warn only if las is genuinely unreachable
if ! command -v las &>/dev/null \
   && [ ! -f "/opt/homebrew/bin/las" ] \
   && [ ! -f "/usr/local/bin/las" ]; then
    echo ""
    echo "  ⚠️  'las' not found in PATH. Add this to ~/.zshrc and reopen your terminal:"
    echo "       export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo ""
echo "Done! Start with:"
echo "  las start"
echo "  las status"
