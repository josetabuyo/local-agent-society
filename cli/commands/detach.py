"""`las detach` — a session with no terminal (docs/adr/0006).

Starts `las-bridge proc` in the background with the agent's configured
command: the bridge runs that command once and speaks JSON lines with it.
LAS opens it, closes it and keeps its log; what thinks inside is not LAS's.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import click

from cli import api
from cli.agent_config import read_agent_config, write_agent_config
from cli.commands import complete_agent_names
from cli.commands._agent_common import resolve_agent_name
from cli.commands.bridge import bridge_argv
from cli.path_utils import agent_config_path

LOG_DIR = Path(os.getenv("LAS_SESSION_LOG_DIR", str(Path.home() / ".las" / "logs" / "sessions")))
# What `las detach` suggests when the agent has no long-lived command yet —
# Pulpo's conversational agent on a local model, speaking the ADR 0006 stdio
# contract. Any command that honours it works.
SUGGESTED_COMMAND = "pulpo agent run"
STARTUP_WAIT_S = 3.0


def agent_dir_of(name: str) -> Path:
    entry = (api.get("/agents") or {}).get(name) or {}
    if not entry.get("path"):
        click.echo(f"Error: agent {name!r} is not registered.", err=True)
        raise SystemExit(1)
    return Path(entry["path"])


def detached_sessions(name: str) -> list:
    view = api.get(f"/agents/{name}/sessions") or {}
    return [s for s in view.get("sessions", []) if s.get("detached")]


def new_log_path(name: str, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return LOG_DIR / f"{name}-{stamp}.log"


def latest_log(name: str) -> Path | None:
    logs = sorted(LOG_DIR.glob(f"{name}-*.log"))
    return logs[-1] if logs else None


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


def login_shell() -> str:
    """The user's login shell: `shell -lc CMD` must find what their terminal finds
    (~/.local/bin/pulpo…) even when started from the backend's launchd service."""
    if os.environ.get("SHELL"):
        return os.environ["SHELL"]
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
    except (ImportError, KeyError):
        return "/bin/sh"


class DetachError(RuntimeError):
    pass


def open_detached(name: str, agent_dir: Path, config: dict, command: str, *, each: bool = False, sessions=detached_sessions) -> tuple:
    """Start `command` as a detached session of `name`; (pid, log path). Raises DetachError if it dies right away.

    each=False: one long-lived process speaking JSON lines (bridge sink `proc`).
    each=True: the command runs once per message, text on stdin (sink `exec`)."""
    log_path = new_log_path(name)
    env = {**os.environ, "LAS_LOCALE": config.get("locale", "")}
    if sys.platform != "win32":
        env["SHELL"] = login_shell()
    proc = spawn_detached(bridge_argv("exec" if each else "proc", name, ["--exec", command, "--log", str(log_path)]), cwd=agent_dir, log_path=log_path, env=env)
    deadline = time.time() + STARTUP_WAIT_S
    while time.time() < deadline:
        if proc.poll() is not None:
            raise DetachError(f"it exited right away ({proc.returncode}). Log: {log_path}")
        if any(s.get("pid") == proc.pid for s in sessions(name)):
            break
        time.sleep(0.2)
    return proc.pid, log_path


def _open(name: str, command: str | None, each: bool = False) -> None:
    agent_dir = agent_dir_of(name)
    path = agent_config_path(agent_dir)
    config = read_agent_config(path) if path else {}
    if command:
        config["detached"] = {**(config.get("detached") or {}), "command": command}
        write_agent_config(path, config)
    command = (config.get("detached") or {}).get("command")
    if not command:
        click.echo(f"{name} has no detached command yet. Set one, e.g.:\n  las detach --cmd \"{SUGGESTED_COMMAND}\"", err=True)
        raise SystemExit(1)
    try:
        pid, log_path = open_detached(name, agent_dir, config, command, each=each)
    except DetachError as err:
        click.echo(f"Error: {err}", err=True)
        raise SystemExit(1)
    click.echo(f"{name}: detached `{command}` (pid {pid}). Log: {log_path}")
    click.echo("  las detach --log   ·   las detach --stop")


def _stop(name: str) -> None:
    sessions = detached_sessions(name)
    if not sessions:
        click.echo(f"{name}: no detached session running.")
        return
    for s in sessions:
        api.post(f"/agents/{name}/sessions/{s['sid']}/close")
        click.echo(f"{name}: closed {s['runtime']} ({s['sid']}).")


def _log(name: str, follow: bool) -> None:
    running = [s["detached"].get("log") for s in detached_sessions(name) if s["detached"].get("log")]
    log = Path(running[0]) if running else latest_log(name)
    if not log or not log.exists():
        click.echo(f"{name}: no detached session log yet.")
        return
    click.echo(f"── {log}", err=True)
    if follow and sys.platform != "win32":
        os.execvp("tail", ["tail", "-n", "50", "-f", str(log)])
    lines = log.read_text(errors="replace").splitlines()
    click.echo("\n".join(lines[-50:]))


@click.command("detach")
@click.argument("name", required=False, shell_complete=complete_agent_names)
@click.option("--cmd", "command", default=None, help=f'The command to run (saved in .las-agent.json → detached.command), e.g. "{SUGGESTED_COMMAND}".')
@click.option("--each", is_flag=True, help="One run of the command PER MESSAGE (text on stdin, its output is the answer), e.g. `pulpo agent`.")
@click.option("--stop", is_flag=True, help="Close this agent's detached session(s).")
@click.option("--log", "show_log", is_flag=True, help="Show the detached session's log.")
@click.option("-f", "--follow", is_flag=True, help="With --log: keep following it.")
def detach_cmd(name, command, each, stop, show_log, follow):
    """Open a session with no terminal: any command that speaks the LAS contract (docs/adr/0006).

    \b
      las detach --cmd "pulpo agent run"   # set the command and open it
      las detach --each --cmd "pulpo agent" # one run per message instead
      las detach                           # open it again
      las detach --log [-f]                # what it printed
      las detach --stop                    # close it (also ✕ in the widget's 👥)
    """
    name = resolve_agent_name(name)
    if stop:
        _stop(name)
    elif show_log:
        _log(name, follow)
    else:
        _open(name, command, each)
