import click
from cli import api


@click.group()
def queue():
    """Manage the TTS speech queue."""


@queue.command("ls")
def queue_ls():
    """Show pending items in the TTS queue."""
    data = api.get("/queue")
    if not data:
        click.echo("Queue is empty.")
        return
    for i, item in enumerate(data, 1):
        click.echo(f"{i}. [{item.get('name','?')}] {item.get('voice','?')}: {item.get('text','')}")


@queue.command("clear")
def queue_clear():
    """Clear all pending TTS messages."""
    api.delete("/queue")
    click.echo("Queue cleared.")
