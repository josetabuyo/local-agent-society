"""`las <command…>` — a command connected to an agent, with no terminal (docs/adr/0006).

Starts `las-bridge exec` in the background: every message to the session runs
the command once with the text as one more argument (`echo Recibido: '<text>'`),
and what it prints is the answer. LAS starts it, closes it (✕ in 👥) and keeps
its log (📄); what thinks inside is not LAS's.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from cli import api
from cli.commands.bridge import bridge_argv

LOG_DIR = Path(os.getenv("LAS_SESSION_LOG_DIR", str(Path.home() / ".las" / "logs" / "sessions")))
STARTUP_WAIT_S = 3.0


class ConnectError(RuntimeError):
    pass


def agent_dir_of(name: str) -> Path:
    entry = (api.get("/agents") or {}).get(name) or {}
    if not entry.get("path"):
        raise ConnectError(f"agent {name!r} is not registered")
    return Path(entry["path"])


def detached_sessions(name: str) -> list:
    view = api.get(f"/agents/{name}/sessions") or {}
    return [s for s in view.get("sessions", []) if s.get("detached")]


def new_log_path(name: str, now: datetime | None = None) -> Path:
    return LOG_DIR / f"{name}-{(now or datetime.now()).strftime('%Y%m%d-%H%M%S')}.log"


def login_shell() -> str:
    """The user's login shell: `shell -lc CMD` must find what their terminal finds (~/.local/bin/…)."""
    if os.environ.get("SHELL"):
        return os.environ["SHELL"]
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
    except (ImportError, KeyError):
        return "/bin/sh"


def spawn_detached(argv: list, *, cwd: Path, log_path: Path, env: dict) -> subprocess.Popen:
    """Fully detached: no tty, own session/process group, stdio to the log. Cross-platform."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab", buffering=0)
    kwargs = {"cwd": str(cwd), "stdin": subprocess.DEVNULL, "stdout": log, "stderr": log, "env": env}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def connect(name: str, agent_dir: Path, command: str, *, locale: str = "", sessions=detached_sessions) -> tuple:
    """Start `command` as a detached session of `name`; (pid, log path). Raises ConnectError if it dies right away."""
    log_path = new_log_path(name)
    env = {**os.environ, "LAS_LOCALE": locale}
    if sys.platform != "win32":
        env["SHELL"] = login_shell()
    argv = bridge_argv("exec", name, ["--exec", command, "--text-as", "arg", "--log", str(log_path)])
    proc = spawn_detached(argv, cwd=agent_dir, log_path=log_path, env=env)
    deadline = time.time() + STARTUP_WAIT_S
    while time.time() < deadline:
        if proc.poll() is not None:
            raise ConnectError(f"it exited right away ({proc.returncode}). Log: {log_path}")
        if any(s.get("pid") == proc.pid for s in sessions(name)):
            break
        time.sleep(0.2)
    return proc.pid, log_path
