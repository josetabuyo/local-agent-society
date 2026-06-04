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
    click.echo(f"{'Port':<8} {'Agent':<20} {'Description'}")
    click.echo("-" * 50)
    for port, info in data.items():
        click.echo(f":{port:<7} {info.get('local_agent','?'):<20} {info.get('description','')}")


@ports.command("free")
def ports_free():
    """Get a free port from the registry."""
    data = api.get("/ports/free")
    click.echo(data.get("port"))
