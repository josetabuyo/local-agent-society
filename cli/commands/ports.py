import click
from cli import api


@click.group()
def ports():
    """Manage port registry."""


@ports.command("ls")
def ports_ls():
    """List registered ports."""
    data = api.get("/ports")
    if not data:
        click.echo("No ports registered.")
        return
    click.echo(f"{'Port':<8} {'Agent':<20} {'App'}")
    click.echo("-" * 54)
    for port, info in sorted(data.items(), key=lambda x: int(x[0])):
        click.echo(f":{port:<7} {info.get('local_agent','?'):<20} {info.get('app','')}")


@ports.command("free")
@click.option("--start", default=9000, help="Range start (default 9000)")
@click.option("--end",   default=9999, help="Range end (default 9999)")
def ports_free(start, end):
    """Get a free port from the registry."""
    data = api.get(f"/ports/free?start={start}&end={end}")
    click.echo(data.get("port"))


@ports.command("claim")
@click.argument("app")
@click.option("--port", default=None, type=int, help="Desired port (omit for auto-assign)")
@click.option("--start", default=9000, help="Range start for auto-assign (default 9000)")
@click.option("--end",   default=9999, help="Range end for auto-assign (default 9999)")
def ports_claim(app, port, start, end):
    """Atomically claim a port (checks + registers in one step). Prints the port."""
    import json, sys
    from pathlib import Path
    agent_json = Path.cwd() / ".agent.json"
    agent_name = "CLI"
    if agent_json.exists():
        try:
            agent_name = json.loads(agent_json.read_text()).get("name", "CLI")
        except Exception:
            pass
    payload = {
        "app": app,
        "local_agent": agent_name,
        "path": str(Path.cwd()),
        "start": start,
        "end": end,
    }
    if port is not None:
        payload["port"] = port
    data = api.post("/ports/claim", payload)
    click.echo(data.get("port"))


@ports.command("release")
@click.argument("port", type=int)
def ports_release(port):
    """Release a registered port."""
    api.delete(f"/ports/{port}")
    click.echo(f"Port {port} released.")
