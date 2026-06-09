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
    """List all available voices with their language."""
    data = api.get("/voices")
    for v in data.get("voices", []):
        if isinstance(v, dict):
            click.echo(f"{v['flag']}  {v['name']:<30} {v['lang']}")
        else:
            click.echo(v)


@voices.command("info")
@click.argument("name")
def voice_info(name):
    """Show language info for a specific voice."""
    data = api.get(f"/voices/{name}")
    click.echo(f"{data['flag']}  {data['name']}  ·  {data['lang']}")
