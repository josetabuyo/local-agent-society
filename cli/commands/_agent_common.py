"""Shared helpers for cli/commands/agents.py.

Centralizes the two pieces of logic that were previously duplicated across
multiple subcommands: resolving an agent name from the current working
directory, and inferring a locale from a TTS voice name.
"""
import json
from pathlib import Path

import click

from cli import api
from cli.path_utils import find_nearest_agent_dir


def _agent_name_from_cwd():
    """Best-effort lookup of the agent name for the current directory's .agent.json."""
    agent_dir = find_nearest_agent_dir(Path.cwd())
    if agent_dir:
        try:
            return json.loads((Path(agent_dir) / ".agent.json").read_text()).get("name")
        except Exception:
            pass
    return None


def resolve_agent_name(name, *, err: bool = False) -> str:
    """Return `name` if given, else infer it from .agent.json in the cwd.

    On failure, echoes the standard error message (matching prior per-command
    behavior) and raises SystemExit(1).
    """
    if name:
        return name
    resolved = _agent_name_from_cwd()
    if resolved:
        return resolved
    click.echo("Error: no agent name given and no .agent.json in current directory.", err=err)
    raise SystemExit(1)


def infer_locale(voice: str) -> str:
    """Return a sensible locale code for a TTS voice name."""
    try:
        return api.get(f"/voices/{voice}").get("lang", "en-US")
    except Exception:
        return "en-US"
