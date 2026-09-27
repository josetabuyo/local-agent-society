"""`las bridge` / `las claude` — deliver this agent's vortexia mailbox into
a session runtime.

The consumer itself (mailbox session, interceptor pipeline, sinks) is ONE
implementation, in Node: bridge/bin/las-bridge.js (see docs/adr/0004). This
module only knows how to launch it for a given sink, where its status file
lives, and how to register it with Claude Code as a channel.

Sinks:
  claude   Claude Code channel — normally started by Claude Code itself from
           ~/.claude.json (see `las bridge install`); run by hand only to debug
  stdout   one JSON line per message (a script, a log, a plain terminal)
  shell    a terminal with no AI in it: print messages, offer kind="command"
           ones to run in the agent's folder (confirmed on the TTY)
  exec     run any command per message — Codex, a local model, a router —
           with the text on stdin, and send its output back to the sender
"""
import json
import os
import shutil
import sys
from pathlib import Path

import click

from cli.commands import complete_agent_names
from cli.commands._agent_common import resolve_agent_name

REPO = Path(__file__).resolve().parents[2]
BRIDGE_BIN = REPO / "bridge" / "bin" / "las-bridge.js"
SESSION_DIR = REPO / "session"

# Research-preview flag: custom channels aren't on Claude Code's allowlist
# yet, so every session that should receive the mailbox must be started with
# it. `las claude` exists so nobody types it by hand.
CLAUDE_CHANNEL_FLAG = "--dangerously-load-development-channels"
MCP_SERVER_NAME = "las"
CLAUDE_CHANNEL_SERVER = f"server:{MCP_SERVER_NAME}"


def claude_config_path() -> Path:
    """Claude Code's user-level config (mcpServers live here, not in settings.json)."""
    return Path(os.environ.get("LAS_CLAUDE_CONFIG") or (Path.home() / ".claude.json"))


def _node() -> str:
    node = shutil.which("node")
    if not node:
        click.echo("Error: node not found on PATH — the bridge is a Node program (see bridge/).", err=True)
        raise SystemExit(1)
    return node


def _exec(argv):
    """Replace this process — the bridge owns stdio from here on (for the
    claude sink stdout IS the MCP wire)."""
    os.execvp(argv[0], argv)


def bridge_argv(sink: str, name: str, extra=()) -> list:
    return [_node(), str(BRIDGE_BIN), sink, "--agent", name, *extra]


def _common(extra: list, intercept_url, port):
    if intercept_url:
        extra += ["--intercept-url", intercept_url]
    if port:
        extra += ["--port", str(port)]
    return extra


@click.group()
def bridge():
    """Deliver this agent's vortexia mailbox into a session runtime (Claude channel, shell, any command)."""


_name_arg = click.argument("name", required=False, shell_complete=complete_agent_names)
_intercept = click.option("--intercept-url", default=None, help="First-decision hook: POST each message here first (fails open).")
_port = click.option("--port", default=None, type=int, help="Broker MQTT port (default: vortexia.port.json, then the registry).")


@bridge.command("claude")
@_name_arg
@_intercept
@_port
def bridge_claude(name, intercept_url, port):
    """Run the Claude Code channel server by hand (debugging; Claude Code normally starts it)."""
    name = resolve_agent_name(name)
    _exec(bridge_argv("claude", name, _common([], intercept_url, port)))


@bridge.command("stdout")
@_name_arg
@_intercept
@_port
def bridge_stdout(name, intercept_url, port):
    """Print one JSON line per message (what `las agent listen` printed)."""
    name = resolve_agent_name(name)
    _exec(bridge_argv("stdout", name, _common([], intercept_url, port)))


@bridge.command("shell")
@_name_arg
@click.option("--yes", is_flag=True, help="Run kind=command messages without asking on the TTY.")
@click.option("--all", "run_all", is_flag=True, help="Offer EVERY message to run, not only kind=command.")
@_intercept
@_port
def bridge_shell(name, yes, run_all, intercept_url, port):
    """A terminal with no AI: print messages, run the ones that are commands (after a y/N)."""
    name = resolve_agent_name(name)
    extra = (["--yes"] if yes else []) + (["--all"] if run_all else [])
    _exec(bridge_argv("shell", name, _common(extra, intercept_url, port)))


@bridge.command("exec")
@_name_arg
@click.option("--exec", "command", required=True, help='Command run per message, text on stdin, e.g. --exec "codex exec -".')
@_intercept
@_port
def bridge_exec(name, command, intercept_url, port):
    """Feed every message to a command (Codex, a local model, a router) and send its output back."""
    name = resolve_agent_name(name)
    _exec(bridge_argv("exec", name, _common(["--exec", command], intercept_url, port)))


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def read_status(name: str) -> dict | None:
    path = SESSION_DIR / f"bridge-{name}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


@bridge.command("status")
@_name_arg
def bridge_status(name):
    """Is a bridge delivering this agent's mailbox right now? Exit 0 only when one is running AND armed."""
    name = resolve_agent_name(name)
    status = read_status(name)
    if not status or not _pid_alive(status.get("pid")):
        click.echo(f"{name}: no bridge running — messages wait in the mailbox (start Claude with `las claude`).")
        raise SystemExit(1)
    armed = bool(status.get("armed"))
    sink = status.get("sink", "?")
    delivered = status.get("delivered", 0)
    state = "armed" if armed else "waiting for the session to ack the channel probe"
    click.echo(f"{name}: {sink} bridge pid {status.get('pid')} — {state}, {delivered} delivered.")
    raise SystemExit(0 if armed else 1)


def mcp_server_entry() -> dict:
    return {"command": _node(), "args": [str(BRIDGE_BIN), "claude"]}


@bridge.command("install")
@click.option("--uninstall", is_flag=True, help="Remove the `las` MCP server entry instead.")
def bridge_install(uninstall):
    """Register the bridge as the `las` MCP server in ~/.claude.json (user-level, so every agent folder gets it)."""
    path = claude_config_path()
    try:
        config = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        click.echo(f"Error: {path} is not valid JSON — not touching it.", err=True)
        raise SystemExit(1)
    servers = config.setdefault("mcpServers", {})
    if uninstall:
        removed = servers.pop(MCP_SERVER_NAME, None) is not None
        path.write_text(json.dumps(config, indent=2) + "\n")
        click.echo(f"{path}: `{MCP_SERVER_NAME}` MCP server {'removed' if removed else 'was not registered'}.")
        return
    entry = mcp_server_entry()
    if servers.get(MCP_SERVER_NAME) == entry:
        click.echo(f"{path}: `{MCP_SERVER_NAME}` MCP server already registered.")
    else:
        servers[MCP_SERVER_NAME] = entry
        path.write_text(json.dumps(config, indent=2) + "\n")
        click.echo(f"{path}: `{MCP_SERVER_NAME}` MCP server registered -> {entry['command']} {' '.join(entry['args'])}")
    click.echo(f"Start sessions with `las claude` (adds {CLAUDE_CHANNEL_FLAG} {CLAUDE_CHANNEL_SERVER}).")


@click.command("claude", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def claude_cmd(args):
    """Start Claude Code with the LAS channel enabled (all other arguments pass through)."""
    if not shutil.which("claude"):
        click.echo("Error: claude not found on PATH.", err=True)
        raise SystemExit(1)
    _exec(["claude", CLAUDE_CHANNEL_FLAG, CLAUDE_CHANNEL_SERVER, *args])
