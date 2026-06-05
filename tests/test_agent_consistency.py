#!/usr/bin/env python3
"""
Verifies that each registered agent has its infrastructure active.
Fails if something is declared but not running or misconfigured.

Usage: python3 tests/test_agent_consistency.py
"""
import json
import sys
import urllib.request
from pathlib import Path

BACKEND = "http://localhost:8700"


def registered_agents() -> dict:
    try:
        with urllib.request.urlopen(f"{BACKEND}/agents", timeout=3) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"FAIL  backend unreachable ({e})")
        sys.exit(1)


def check_skill_new_local_agent(install_dir: Path) -> list[str]:
    skill = install_dir / "skills" / "new-local-agent" / "SKILL.md"
    if not skill.exists():
        return []
    text = skill.read_text()
    errors = []
    if "localagentsociety://" not in text:
        errors.append("new-local-agent skill does not use open 'localagentsociety://AGENT' to launch widgets")
    return errors


def check_agent(name: str, info: dict) -> list[str]:
    path = Path(info.get("path", ""))
    errors = []

    if not (path / ".agent.json").exists():
        errors.append(f"missing .agent.json in {path}")

    claude_md = path / "CLAUDE.md"
    if claude_md.exists():
        text = claude_md.read_text()
        if "say -v" in text:
            errors.append("CLAUDE.md uses 'say -v' directly — must use POST /queue/speak")

    for settings_file in [path / ".claude" / "settings.json", path / ".claude" / "settings.local.json"]:
        if settings_file.exists():
            if "say -v" in settings_file.read_text():
                errors.append(f"{settings_file.name} has a hook using 'say -v' directly")

    try:
        with urllib.request.urlopen(f"{BACKEND}/health", timeout=2) as r:
            pass
    except Exception:
        errors.append("backend not responding at http://localhost:8700")

    return errors


def check_inject_applescript(install_dir: Path) -> list[str]:
    """Verify the inject function sends Enter within the iTerm2 tell block (not via System Events)."""
    main_py = install_dir / "backend" / "main.py"
    if not main_py.exists():
        return []
    text = main_py.read_text()
    errors = []
    if "ASCII character 13" not in text:
        errors.append(
            "backend/_inject_via_iterm does not use ASCII character 13 for Enter — "
            "Enter will not be pressed automatically after voice injection"
        )
    if "System Events" in text and "key code 36" in text:
        errors.append(
            "backend/_inject_via_iterm still uses System Events key code 36 — "
            "this causes intermittent failures when iTerm2 frontmost session differs from target"
        )
    return errors


def main():
    agents = registered_agents()
    all_errors: dict[str, list[str]] = {}

    install_dir = Path(__file__).parent.parent

    skill_errors = check_skill_new_local_agent(install_dir)
    if skill_errors:
        all_errors["[skills]"] = skill_errors

    inject_errors = check_inject_applescript(install_dir)
    if inject_errors:
        all_errors["[backend]"] = inject_errors

    for name, info in agents.items():
        errs = check_agent(name, info)
        if errs:
            all_errors[name] = errs

    if not all_errors:
        print(f"OK  {len(agents)} agents verified, all consistent")
        for name in sorted(agents):
            members = agents[name].get("members", [])
            print(f"    {name}: {' · '.join(m.upper() for m in members)}")
        sys.exit(0)
    else:
        print("FAIL  inconsistencies found:\n")
        for name, errs in all_errors.items():
            print(f"  {name}:")
            for e in errs:
                print(f"    - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
