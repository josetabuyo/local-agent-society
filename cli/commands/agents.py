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


@agent.command("restore")
@click.argument("name", required=False)
def restore(name):
    """Restore .agent.json from backend registry (use if accidentally deleted)."""
    cwd = Path.cwd()
    agents = api.get("/agents")
    if not agents:
        click.echo("Error: no agents registered in backend.")
        raise SystemExit(1)

    if name:
        info = agents.get(name)
        if not info:
            click.echo(f"Error: agent '{name}' not found in backend.")
            raise SystemExit(1)
    else:
        info = next((v for v in agents.values() if Path(v.get("path", "")) == cwd), None)
        if not info:
            click.echo(f"Error: no agent registered for {cwd}. Pass NAME explicitly.")
            raise SystemExit(1)
        name = info.get("name") or next(k for k, v in agents.items() if v is info)

    target = cwd / ".agent.json"
    data = {
        "name": name,
        "voice": info.get("voice", "Samantha"),
        "pronunciation": info.get("pronunciation") or name,
        "backend_url": info.get("backend_url", "http://localhost:8700"),
        "frontend_url": info.get("frontend_url", f"http://localhost:8700/widget/{name}"),
        "created": info.get("registered_at", "")[:10],
    }
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    click.echo(f"Restored .agent.json for '{name}' (voice: {data['voice']}).")


@agent.command("sync")
def sync():
    """Sync .agent.json in the current directory to the backend registry."""
    p = Path.cwd() / ".agent.json"
    if not p.exists():
        click.echo("Error: no .agent.json in current directory.")
        raise SystemExit(1)
    d = json.loads(p.read_text())
    payload = {
        "name":          d["name"],
        "voice":         d.get("voice", "Samantha"),
        "path":          str(Path.cwd()),
        "backend_url":   d.get("backend_url", "http://localhost:8700"),
        "frontend_url":  d.get("frontend_url", f"http://localhost:8700/widget/{d['name']}"),
        "pronunciation": d.get("pronunciation"),
    }
    api.post("/agents", payload)
    click.echo(f"Synced '{d['name']}' to backend.")


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
