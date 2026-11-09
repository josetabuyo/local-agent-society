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
@click.option("--name", default=None, help="Speaker label (default: from agent config or CLI)")
def speak(text, name):
    """Enqueue a TTS message — spoken by NAME's widget, in its own Kokoro voice (`tts_voice`)."""
    agent = _agent_json()
    name = name or agent.get("name", "CLI")
    api.post("/queue/speak", {"text": text, "name": name})
    click.echo(f"Queued [{name}]: {text}")
