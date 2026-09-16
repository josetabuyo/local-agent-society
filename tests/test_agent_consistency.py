"""
Verifies that each registered agent has its infrastructure active.
Fails if something is declared but not running or misconfigured.
"""
import json
import urllib.request
from pathlib import Path

BACKEND = "http://localhost:8700"
ROOT = Path(__file__).parent.parent


def _agents() -> dict:
    with urllib.request.urlopen(f"{BACKEND}/agents", timeout=3) as r:
        return json.loads(r.read())


def test_backend_reachable():
    """Backend must respond at http://localhost:8700/health."""
    try:
        with urllib.request.urlopen(f"{BACKEND}/health", timeout=2):
            pass
    except Exception as e:
        raise AssertionError(f"Backend not responding at {BACKEND}: {e}")


def test_inject_uses_ascii_13_for_enter():
    """_inject_via_iterm must use 'ASCII character 13' for Enter — not System Events."""
    text = (ROOT / "backend" / "main.py").read_text()
    assert "ASCII character 13" in text, \
        "_inject_via_iterm does not use ASCII character 13 — Enter won't be pressed after injection"


def test_inject_does_not_use_system_events_key_code():
    """_inject_via_iterm must not use System Events key code 36 — causes intermittent failures."""
    text = (ROOT / "backend" / "main.py").read_text()
    assert not ("System Events" in text and "key code 36" in text), \
        "_inject_via_iterm still uses System Events key code 36"


def test_registered_agents_have_agent_json():
    """Each registered agent must have a .las-agent.json (or legacy .agent.json) at its declared project path."""
    missing = [
        name for name, info in _agents().items()
        if not (Path(info.get("path", "")) / ".las-agent.json").exists()
        and not (Path(info.get("path", "")) / ".agent.json").exists()
    ]
    assert not missing, f"Missing agent config for: {', '.join(missing)}"


def test_install_sh_purges_legacy_watcher_plists():
    """install.sh must detect and remove orphaned *.haiku.plist / *.opus.plist from ~/Library/LaunchAgents.

    These were left behind by a pre-TTY-injection system where each project
    ran haiku-watcher.sh and opus-watcher.sh via launchd. The scripts no
    longer exist; install.sh must clean up any survivors.
    """
    text = (ROOT / "install.sh").read_text()
    assert "haiku.plist" in text and "opus.plist" in text, \
        "install.sh does not scan for legacy haiku/opus watcher plists"
    assert "launchctl unload" in text, \
        "install.sh does not unload plists before deleting them"
    assert 'rm -f "$plist"' in text or "rm -f" in text, \
        "install.sh does not delete the orphaned plist files"


def test_stop_sh_waits_for_widget_processes_to_exit_before_returning():
    """stop.sh must not fire-and-forget `kill` at the widget processes.

    update.sh/start.sh run electron-builder right after stop.sh to overwrite
    dist/mac-arm64/Local Agent Society.app. If stop.sh returns immediately
    after sending SIGTERM, old helper processes (renderer/GPU) can still be
    shutting down and holding file handles into that bundle when the rebuild
    starts, corrupting the freshly-built .app so it silently fails to launch
    (the exact bug reported by System on uy-mac, 2026-09-16). stop.sh must
    poll until the processes are actually gone, with a SIGKILL fallback for
    ones that don't exit in time.
    """
    text = (ROOT / "stop.sh").read_text()
    assert "kill $PIDS" in text or "kill $PIDS " in text, \
        "stop.sh does not send SIGTERM to the collected widget PIDs"
    assert "pgrep -f \"$WIDGET_PATTERN\"" in text and text.count('pgrep -f "$WIDGET_PATTERN"') >= 2, \
        "stop.sh does not re-check for the widget processes after killing them " \
        "— it must poll in a loop, not fire-and-forget"
    assert "kill -9" in text, \
        "stop.sh has no SIGKILL fallback for widget processes that don't exit in time"


def test_registered_agents_settings_no_direct_say_hooks():
    """No registered agent's hook settings should invoke 'say -v' directly — use POST /queue/speak."""
    violations = []
    for name, info in _agents().items():
        path = Path(info.get("path", ""))
        for sf in [path / ".claude" / "settings.json", path / ".claude" / "settings.local.json"]:
            if sf.exists():
                text = sf.read_text()
                if "say -v" in text:
                    violations.append(f"{name}/{sf.name}")
    assert not violations, f"Hook settings use 'say -v' directly in: {', '.join(violations)}"


