"""`las map` — an agent's map (docs/adr/0007): its sessions, friends and the elements added by hand.

The map window reads it; this is how elements get on it. Every command here
is a thin call to the backend's /agents/{name}/map, so the CLI, the API and
the window always agree.
"""
import subprocess
from pathlib import Path
from urllib.parse import quote

import click

from cli import api
from cli.commands import complete_agent_names
from cli.commands._agent_common import resolve_agent_name


def _base(name: str) -> str:
    return f"/agents/{quote(name, safe='')}/map"


def _print(view: dict) -> None:
    rows = view.get("elements", [])
    name = view.get("agent", "?")
    if not rows:
        click.echo(f"{name}: nothing on the map yet — `las map add repo PATH` or `las map add url URL`")
        return
    for e in rows:
        if e["type"] == "repo":
            state = (f"{e.get('github') or 'no GitHub remote'} · {e.get('branch') or '?'}"
                     if e.get("exists") else "[missing — not a git folder any more]")
            click.echo(f"repo  {e['label']:<24} {state}")
        else:
            click.echo(f"url   {e['label']:<24} {e['url']}")
        click.echo(f"      id: {e['id']}")


@click.group("map", invoke_without_command=True)
@click.option("--agent", "name", default=None, shell_complete=complete_agent_names, help="Whose map (default: the agent in the cwd).")
@click.pass_context
def map_group(ctx, name):
    """An agent's map: open its window, list it, add repos and URLs to it, remove them.

    \b
      las map                                   # open the map window of the agent in the cwd
      las map open Pulpo                        # someone else's
      las map list                              # the added elements, in the terminal
      las map add repo .                        # this git folder
      las map add repo ~/Development/pulpo --label Pulpo
      las map add url https://github.com/josetabuyo/local-agent-society/pulls --label PRs
      las map remove repo:relay-ros             # by id, as `las map` prints it

    Stored as `map` in the agent's .las-agent.json (a repo inside the agent's
    folder is kept relative to it). Sessions and friends are on the map too,
    but they come from `las agent sessions` / `las agent friends`, not from here.
    """
    ctx.ensure_object(dict)
    ctx.obj["agent"] = name
    if ctx.invoked_subcommand is None:
        _open(resolve_agent_name(name))


def _open(name: str) -> None:
    # Like `las widget`: the app recreates the window on the current Space.
    subprocess.run(["open", f"localagentsociety://{quote(name, safe='')}?action=map"], check=False)
    click.echo(f"Map opened for {name} — add elements with `las map add`.")


@map_group.command("open")
@click.argument("name", required=False, shell_complete=complete_agent_names)
@click.pass_context
def map_open(ctx, name):
    """Open the map window (closes and reopens it on the current Space)."""
    _open(resolve_agent_name(name or (ctx.obj or {}).get("agent")))


@map_group.command("list")
@click.argument("name", required=False, shell_complete=complete_agent_names)
@click.pass_context
def map_list(ctx, name):
    """Show the elements on an agent's map."""
    _print(api.get(_base(resolve_agent_name(name or (ctx.obj or {}).get("agent")))))


@map_group.group("add")
def map_add():
    """Add an element to the map."""


@map_add.command("repo")
@click.argument("path", default=".", type=click.Path(file_okay=False))
@click.option("--label", default=None, help="Name on the map (default: the folder's name).")
@click.pass_context
def map_add_repo(ctx, path, label):
    """Add a local git repository (default: the cwd)."""
    name = resolve_agent_name((ctx.obj or {}).get("agent"))
    _print(api.post(_base(name), {"type": "repo", "path": str(Path(path).expanduser().resolve()), "label": label}))


@map_add.command("url")
@click.argument("url")
@click.option("--label", default=None, help="Name on the map (default: the URL without its scheme).")
@click.pass_context
def map_add_url(ctx, url, label):
    """Add a URL."""
    name = resolve_agent_name((ctx.obj or {}).get("agent"))
    _print(api.post(_base(name), {"type": "url", "url": url, "label": label}))


@map_group.command("remove")
@click.argument("element_id")
@click.pass_context
def map_remove(ctx, element_id):
    """Remove an element by its id (`repo:<path>` / `url:<url>`, as `las map` prints it)."""
    name = resolve_agent_name((ctx.obj or {}).get("agent"))
    _print(api.delete(f"{_base(name)}?id={quote(element_id, safe='')}"))
