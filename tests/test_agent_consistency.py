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


def test_new_local_agent_skill_opens_widget():
    """new-local-agent skill must open widgets via las widget (which uses localagentsociety:// internally)."""
    skill = ROOT / "skills" / "new-local-agent" / "SKILL.md"
    if not skill.exists():
        return
    text = skill.read_text()
    assert "las widget" in text or "localagentsociety://" in text, \
        "new-local-agent skill does not open widgets via las widget or localagentsociety:// URL scheme"


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
    """Each registered agent must have a .agent.json at its declared project path."""
    missing = [
        name for name, info in _agents().items()
        if not (Path(info.get("path", "")) / ".agent.json").exists()
    ]
    assert not missing, f"Missing .agent.json for: {', '.join(missing)}"


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


