"""`las hook …` — the end-of-turn hooks Claude Code and Codex call (cli/turn_hook.py)."""
import json
import sys

import click

from cli import turn_hook


@click.group("hook")
def hook():
    """End-of-turn hooks: make every agent speak its closing report (installed by `las claude`/`las codex`/`las update`)."""


@hook.command("claude-stop")
def claude_stop():
    """Claude Code `Stop` hook: reads the hook JSON on stdin; blocks once when the turn had no `las speak`."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        decision = turn_hook.claude_stop(payload)
    except Exception:
        decision = None  # never get in the way of a session
    if decision:
        click.echo(json.dumps(decision))


@hook.command("codex-notify", context_settings={"ignore_unknown_options": True})
@click.argument("payload", required=False)
def codex_notify(payload):
    """Codex `notify` program: gets the turn JSON as its argument; nudges the codex session when it didn't speak."""
    try:
        turn_hook.codex_notify(json.loads(payload or "{}"))
    except Exception:
        pass


@hook.command("install")
def install():
    """Write both hooks (Claude's settings.json Stop hook, Codex's notify) — idempotent."""
    c = turn_hook.ensure_claude_hook()
    x = turn_hook.ensure_codex_notify()
    click.echo(f"Claude Stop hook: {'ok' if c else 'not written (settings.json unreadable)'}")
    click.echo(f"Codex notify:     {'ok' if x else 'not set (no ~/.codex, or another notify program holds it)'}")
