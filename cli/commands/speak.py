import json
from pathlib import Path
import click
from cli import api
from cli.path_utils import agent_config_path


def _agent_json():
    p = agent_config_path(Path.cwd())
    if p:
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


@click.command()
@click.argument("text")
@click.option("--voice", default=None, help="TTS voice (default: from agent config or Samantha)")
@click.option("--name", default=None, help="Speaker label (default: from agent config or CLI)")
def speak(text, voice, name):
    """Enqueue a TTS message."""
    agent = _agent_json()
    voice = voice or agent.get("voice", "Samantha")
    name = name or agent.get("name", "CLI")
    api.post("/queue/speak", {"text": text, "voice": voice, "name": name})
    click.echo(f"Queued [{name}]: {text}")
