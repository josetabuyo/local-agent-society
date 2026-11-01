"""`las local` — this agent, as a conversational session on a LOCAL model.

Like `las claude` / `las codex` / `las shell`: one command, run in the agent's
folder, that publishes presence, registers this terminal as a session
(runtime "local", through a `las-bridge stdout` child) and hands the terminal
to the agent. See cli/local_agent.py for how a turn is handled.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import click

from cli import local_agent
from cli.commands._agent_common import resolve_agent_name
from cli.commands.bridge import _chain, _common, _sign_terminal, bridge_argv
from cli.path_utils import agent_config_path, find_nearest_agent_dir
from cli.update_notice import print_update_notice

RUNTIME = "local"


def _agent_config(agent_dir: str | None) -> dict:
    path = agent_config_path(agent_dir) if agent_dir else None
    try:
        return json.loads(path.read_text()) if path else {}
    except (OSError, ValueError):
        return {}


def _tty_confirm(prompt: str) -> bool:
    """y/N on the controlling terminal (stdin is busy feeding the conversation)."""
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(f"  ¿Ejecutar {prompt}? [y/N] ")
            tty.flush()
            return tty.readline().strip().lower() in ("y", "s", "yes", "si", "sí")
    except OSError:
        return False


TRUSTED_ORIGINS = ("terminal", "human")   # the human typed or dictated it


def confirm_tool(prompt: str, origin: str, yes: bool, ask=None) -> bool:
    """--yes only covers what the human asked for. A turn from another agent is
    data: always the y/N on the tty, and no tty means no."""
    if yes and origin in TRUSTED_ORIGINS:
        return True
    return (ask or _tty_confirm)(prompt)


@click.command("local")
@click.option("--model", default=None, help=f"Ollama chat model (default: $LAS_LOCAL_MODEL or {local_agent.CHAT_MODEL}).")
@click.option("--no-select", is_flag=True, help="Skip the decision-model selection step: the chat model sees every tool.")
@click.option("--yes", is_flag=True, help="Run shell commands without the y/N — only for turns typed here or dictated; another agent's message always asks.")
@click.option("--no-mailbox", is_flag=True, help="Terminal only: don't register a session or take mailbox messages.")
@click.option("--no-widget", is_flag=True, help="Don't bring this agent's widget to the current Space.")
@click.option("-v", "--verbose", is_flag=True, help="Show the selector's pick, timings and tool calls.")
def local_cmd(model, no_select, yes, no_mailbox, no_widget, verbose):
    """A conversational session on a local model: Ollama chats, LocalModels' decision model picks the tool or skill.

    Type to talk; messages from other agents and the widget mic arrive here too and are answered
    back to whoever sent them. /exit to leave. Skills: markdown files with name/description front
    matter in <agent>/.las-local/skills/ or ~/.las/local-skills/.
    """
    name = resolve_agent_name(None)
    agent_dir = find_nearest_agent_dir(Path.cwd()) or os.getcwd()
    cfg = _agent_config(agent_dir)
    las = shutil.which("las") or "las"
    if not no_mailbox:
        _chain(name, widget=not no_widget)
    print_update_notice()
    _sign_terminal(name, RUNTIME)

    chat_model = model or local_agent.CHAT_MODEL
    log = (lambda line: click.echo(click.style(f"  · {line}", dim=True), err=True)) if verbose else (lambda line: None)
    agent = local_agent.LocalAgent(
        name=name, agent_dir=agent_dir, locale=cfg.get("locale") or "es",
        scope=(cfg.get("long_description") or cfg.get("short_description") or "").strip(),
        tools=local_agent.default_tools(name, agent_dir, las),
        skills=local_agent.load_skills(local_agent.skill_dirs(agent_dir)),
        chat=lambda messages, tools: local_agent.ollama_chat(messages, tools, model=chat_model),
        selector=None if no_select else local_agent.select,
        confirm=lambda prompt, origin: confirm_tool(prompt, origin, yes),
        log=log,
    )
    skills = f", {len(agent.skills)} skills" if agent.skills else ""
    click.echo(f"{name} · local — {chat_model}"
               f"{'' if no_select else ' + selector ' + local_agent.scope_router.ROUTER_URL}"
               f" · {len(agent.tools)} tools{skills}. /exit para salir.")
    argv = None if no_mailbox else bridge_argv("stdout", name, _common(["--runtime", RUNTIME, "--quiet"], None, None))
    raise SystemExit(local_agent.LocalRuntime(agent, bridge_argv=argv, las=las, stdin=sys.stdin).run())
