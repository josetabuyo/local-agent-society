import json
import subprocess
from pathlib import Path
import click
from cli import api


def _agent_name_from_cwd():
    p = Path.cwd() / ".agent.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("name")
        except Exception:
            pass
    return None


@click.group()
def agent():
    """Manage agents."""


@click.command("agents")
def agents_list():
    """List all registered agents."""
    data = api.get("/agents")
    if not data:
        click.echo("No agents registered.")
        return
    click.echo(f"{'Name':<20} {'Voice':<25} {'Path'}")
    click.echo("-" * 70)
    for name, info in data.items():
        click.echo(f"{name:<20} {info.get('voice','?'):<25} {info.get('path','?')}")


@agent.command("inject")
@click.argument("name")
@click.argument("message")
@click.option("--from", "from_agent", default=None, help="Sender name shown in the terminal prefix")
def inject(name, message, from_agent):
    """Inject a message into a live agent terminal."""
    payload = {
        "message": message,
        "source": "agent" if from_agent else "external",
    }
    if from_agent:
        payload["from_agent"] = from_agent
    result = api.post(f"/agents/{name}/inject", payload)
    injected = result.get("injected", False)
    status = "injected into terminal" if injected else "written to inbox (agent not live)"
    click.echo(f"{name}: {status}")


@click.command("widget")
@click.argument("name", required=False)
def widget(name):
    """Reopen the agent widget on the current Space."""
    if not name:
        name = _agent_name_from_cwd()
    if not name:
        click.echo("Error: no agent name given and no .agent.json in current directory.")
        raise SystemExit(1)
    subprocess.run(["open", f"localagentsociety://{name}?action=reopen"], check=False)
    click.echo(f"Widget reopened for {name}.")
