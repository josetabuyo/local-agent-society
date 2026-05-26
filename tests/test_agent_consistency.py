#!/usr/bin/env python3
"""
Verifica que cada agente registrado tiene su infraestructura activa.
Falla si la UI declara algo que no está corriendo o configurado mal.

Uso: python3 tests/test_agent_consistency.py
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
        print(f"FAIL  backend no responde ({e})")
        sys.exit(1)


def check_skill_new_local_agent(install_dir: Path) -> list[str]:
    skill = install_dir / "skills" / "new-local-agent" / "SKILL.md"
    if not skill.exists():
        return []
    text = skill.read_text()
    errors = []
    if "widget/widget " in text and "localagentsociety://" not in text:
        errors.append("new-local-agent skill lanza el binario widget simple en vez del URL scheme — los widgets no tendrán botón ···")
    if "localagentsociety://" not in text:
        errors.append("new-local-agent skill no usa open 'localagentsociety://FAMILY' para lanzar widgets")
    return errors


def check_agent(family: str, info: dict) -> list[str]:
    path = Path(info.get("path", ""))
    errors = []

    # .agent.json presente
    if not (path / ".agent.json").exists():
        errors.append(f"falta .agent.json en {path}")

    # CLAUDE.md: no debe usar 'say -v' ni referencias al viejo sistema inbox/outbox
    claude_md = path / "CLAUDE.md"
    if claude_md.exists():
        text = claude_md.read_text()
        if "say -v" in text:
            errors.append("CLAUDE.md usa 'say -v' directo — debe usar POST /queue/speak")
        if "haiku-inbox" in text or "opus-inbox" in text:
            errors.append("CLAUDE.md referencia el sistema inbox/outbox obsoleto")

    # Settings: no deben tener 'say -v'
    for settings_file in [path / ".claude" / "settings.json", path / ".claude" / "settings.local.json"]:
        if settings_file.exists():
            content = settings_file.read_text()
            if "say -v" in content:
                errors.append(f"{settings_file.name} tiene hook con 'say -v' directo")

    # TTS: backend debe responder
    try:
        with urllib.request.urlopen(f"{BACKEND}/health", timeout=2) as r:
            pass
    except Exception:
        errors.append("backend TTS no responde en http://localhost:8700")

    return errors


def main():
    agents = registered_agents()
    all_errors: dict[str, list[str]] = {}

    # Check skills (install-dir derived from this script's location)
    install_dir = Path(__file__).parent.parent
    skill_errors = check_skill_new_local_agent(install_dir)
    if skill_errors:
        all_errors["[skills]"] = skill_errors

    for family, info in agents.items():
        errs = check_agent(family, info)
        if errs:
            all_errors[family] = errs

    if not all_errors:
        print(f"OK  {len(agents)} agentes verificados, todo consistente")
        for family in sorted(agents):
            members = agents[family].get("members", [])
            print(f"    {family}: {' · '.join(m.upper() for m in members)}")
        sys.exit(0)
    else:
        print("FAIL  inconsistencias encontradas:\n")
        for family, errs in all_errors.items():
            print(f"  {family}:")
            for e in errs:
                print(f"    - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
