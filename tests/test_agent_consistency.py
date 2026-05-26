#!/usr/bin/env python3
"""
Verifica que cada agente registrado tiene toda su infraestructura activa.
Falla si la UI declara algo que no está corriendo.

Uso: python3 tests/test_agent_consistency.py
"""
import json
import subprocess
import sys
from pathlib import Path

BACKEND = "http://localhost:8700"
WATCHER_SCRIPT = Path(__file__).parent.parent / "session"

def launchd_running() -> set[str]:
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    return {line.split()[-1] for line in out.splitlines() if "localagent" in line and line.split()[0] != "-"}

def registered_agents() -> dict:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{BACKEND}/agents", timeout=3) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"FAIL  backend no responde ({e})")
        sys.exit(1)

def check_agent(family: str, info: dict, running: set[str]) -> list[str]:
    slug = family.lower()
    members = info.get("members", [])
    path = Path(info.get("path", ""))
    errors = []

    for member in members:
        if member == "sonnet":
            continue  # sonnet es la sesión interactiva, no necesita watcher

        svc = f"com.localagent.{slug}.{member}"
        if svc not in running:
            errors.append(f"launchd service '{svc}' no está corriendo (declara member '{member}')")

        inbox = path / "session" / f"{member}-inbox.md"
        if not inbox.exists():
            errors.append(f"falta {inbox}")

        outbox = path / "session" / f"{member}-outbox.md"
        if not outbox.exists():
            errors.append(f"falta {outbox}")

    if not (path / "session").is_dir():
        errors.append(f"falta directorio session/ en {path}")

    claude_md = path / "CLAUDE.md"
    if claude_md.exists():
        if "say -v" in claude_md.read_text():
            errors.append(f"CLAUDE.md usa 'say -v' directo — debe usar POST /queue/speak")

    for settings_file in [path / ".claude" / "settings.json", path / ".claude" / "settings.local.json"]:
        if settings_file.exists():
            content = settings_file.read_text()
            if "say -v" in content:
                errors.append(f"{settings_file.name} tiene hook con 'say -v' directo — eliminar o reemplazar con POST /queue/speak")

    return errors

def main():
    agents = registered_agents()
    running = launchd_running()

    all_errors: dict[str, list[str]] = {}

    for family, info in agents.items():
        errs = check_agent(family, info, running)
        if errs:
            all_errors[family] = errs

    if not all_errors:
        print(f"OK  {len(agents)} agentes verificados, todo consistente")
        for family in sorted(agents):
            members = agents[family].get("members", [])
            print(f"    {family}: {' · '.join(m.upper() for m in members)}")
        sys.exit(0)
    else:
        print(f"FAIL  inconsistencias encontradas:\n")
        for family, errs in all_errors.items():
            print(f"  {family}:")
            for e in errs:
                print(f"    - {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
