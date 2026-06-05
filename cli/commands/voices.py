import click
from cli import api


@click.group()
def voices():
    """Query available TTS voices."""


@voices.command("random")
def random_voice():
    """Pick a random unused voice from the registry."""
    data = api.get("/voices/random")
    click.echo(data.get("voice", ""))


@voices.command("list")
def list_voices():
    """List all available voices."""
    data = api.get("/voices")
    for v in data.get("voices", []):
        click.echo(v)
