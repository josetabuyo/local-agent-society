import datetime
import json
import subprocess
from pathlib import Path
import click
from cli import api
from cli.commands import complete_agent_names, complete_voice_names


def _infer_locale(voice: str) -> str:
    """Return a sensible locale code for a TTS voice name."""
    from cli import api
    try:
        return api.get(f"/voices/{voice}").get("lang", "en-US")
    except Exception:
        return "en-US"


def _agent_name_from_cwd():
    current = Path.cwd()
    for directory in [current, *current.parents]:
        p = directory / ".agent.json"
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


@agent.command("new")
@click.argument("name")
@click.option("--voice", default=None, shell_complete=complete_voice_names, help="TTS voice name. Auto-assigned if omitted.")
@click.option("--dir", "target_dir", default=None,
              help="Directory for the agent (default: current directory).")
def new(name, voice, target_dir):
    """Create a new agent: writes .agent.json, registers with backend, launches widget."""
    cwd = Path(target_dir).resolve() if target_dir else Path.cwd()

    # Ensure target dir exists
    cwd.mkdir(parents=True, exist_ok=True)

    # Guard: don't overwrite an existing agent
    agent_file = cwd / ".agent.json"
    if agent_file.exists():
        existing = json.loads(agent_file.read_text()).get("name", "?")
        click.echo(f"Error: {agent_file} already exists (agent '{existing}'). "
                   "Use `las agent rename` or delete it first.")
        raise SystemExit(1)

    # Pick voice
    if voice:
        chosen_voice = voice
    else:
        data = api.get("/voices/random")
        chosen_voice = data.get("voice") or data.get("name", "Samantha")

    # Resolve locale from voice
    try:
        locale = api.get(f"/voices/{chosen_voice}").get("lang", "en-US")
    except SystemExit:
        locale = "en-US"

    # Write .agent.json
    agent_data = {
        "name": name,
        "voice": chosen_voice,
        "locale": locale,
        "pronunciation": name,
        "created": str(datetime.date.today()),
    }
    agent_file.write_text(json.dumps(agent_data, indent=2, ensure_ascii=False))
    click.echo(f"Created {agent_file}")

    # Register with backend
    api.post("/agents", {
        "name": name,
        "voice": chosen_voice,
        "path": str(cwd),
    })
    click.echo(f"Registered '{name}' with backend.")

    # Create session dir
    session_dir = cwd / "session"
    session_dir.mkdir(exist_ok=True)
    (session_dir / "bitacora.md").touch()
    click.echo(f"Created {session_dir}/")

    # Launch widget
    subprocess.run(["open", f"localagentsociety://{name}?action=reopen"], check=False)
    click.echo(f"Widget launched.")

    # Announce
    lang = locale.split("-")[0]
    greeting = f"Hello, I am {name}, ready." if lang != "es" else f"Hola, soy {name}, listo."
    api.post("/queue/speak", {"text": greeting, "voice": chosen_voice, "name": name})

    click.echo(f"\nAgent '{name}' created — voice: {chosen_voice}, locale: {locale}")


@agent.command("restore")
@click.argument("name", required=False, shell_complete=complete_agent_names)
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
    voice = info.get("voice", "Samantha")
    data = {
        "name": name,
        "voice": voice,
        "locale": info.get("locale") or _infer_locale(voice),
        "pronunciation": info.get("pronunciation") or name,
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
        "pronunciation": d.get("pronunciation"),
    }
    api.post("/agents", payload)
    click.echo(f"Synced '{d['name']}' to backend.")


@agent.command("delete")
@click.argument("name", required=False, shell_complete=complete_agent_names)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def delete(name, yes):
    """Unregister an agent from the backend (does not delete files)."""
    if not name:
        name = _agent_name_from_cwd()
    if not name:
        click.echo("Error: no agent name given and no .agent.json in current directory.")
        raise SystemExit(1)
    if not yes:
        click.confirm(f"Unregister '{name}' from the backend?", abort=True)
    api.delete(f"/agents/{name}")
    click.echo(f"Agent '{name}' unregistered.")


@agent.command("focus")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def focus(name):
    """Bring the agent's iTerm2 window to the front."""
    if not name:
        name = _agent_name_from_cwd()
    if not name:
        click.echo("Error: no agent name given and no .agent.json in current directory.")
        raise SystemExit(1)
    result = api.post(f"/agents/{name}/focus", {})
    focused = result.get("focused", False)
    click.echo(f"{name}: {'focused' if focused else 'session not found'}")


@agent.command("inject")
@click.argument("name", shell_complete=complete_agent_names)
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
    queued   = result.get("queued", False)
    drained  = result.get("drained", 0)
    if injected:
        suffix = f" (+ {drained} queued drained)" if drained else ""
        status = f"injected into terminal{suffix}"
    elif queued:
        status = "agent offline — queued for delivery when live"
    else:
        status = "agent not live — not delivered"
    click.echo(f"{name}: {status}")


@agent.command("rename")
@click.argument("old_name", required=False, shell_complete=complete_agent_names)
@click.argument("new_name")
@click.option("--pronunciation", default=None, help="Override pronunciation (defaults to new name).")
def rename(old_name, new_name, pronunciation):
    """Rename an agent in the backend registry and update .agent.json."""
    cwd_agent_file = Path.cwd() / ".agent.json"

    if not old_name:
        old_name = _agent_name_from_cwd()
    if not old_name:
        click.echo("Error: no agent name given and no .agent.json in current directory.")
        raise SystemExit(1)

    result = api.patch(f"/agents/{old_name}", {
        "new_name": new_name,
        **({"pronunciation": pronunciation} if pronunciation else {}),
    })
    click.echo(f"Renamed '{old_name}' → '{new_name}' in backend registry.")

    if cwd_agent_file.exists():
        try:
            d = json.loads(cwd_agent_file.read_text())
            if d.get("name") == old_name:
                d["name"] = new_name
                d.pop("frontend_url", None)
                d.pop("backend_url", None)
                if pronunciation:
                    d["pronunciation"] = pronunciation
                elif d.get("pronunciation") == old_name:
                    d["pronunciation"] = new_name
                cwd_agent_file.write_text(json.dumps(d, indent=2, ensure_ascii=False))
                click.echo(f"Updated .agent.json (name, pronunciation).")
        except Exception as exc:
            click.echo(f"Warning: could not update .agent.json — {exc}")


@agent.command("clean")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def clean(name):
    """Inject /clear into the agent terminal (same as the broom button)."""
    if not name:
        name = _agent_name_from_cwd()
    if not name:
        click.echo("Error: no agent name given and no .agent.json in current directory.")
        raise SystemExit(1)
    result = api.post(f"/agents/{name}/inject", {"message": "/clear", "source": "raw"})
    injected = result.get("injected", False)
    status = "cleared" if injected else "agent not live (not injected)"
    click.echo(f"{name}: {status}")


@agent.command("mute")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def mute(name):
    """Mute an agent's TTS voice."""
    if not name:
        name = _agent_name_from_cwd()
    if not name:
        click.echo("Error: no agent name given and no .agent.json in current directory.")
        raise SystemExit(1)
    api.post(f"/agents/{name}/mute", {})
    click.echo(f"{name}: muted.")


@agent.command("unmute")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def unmute(name):
    """Unmute an agent's TTS voice."""
    if not name:
        name = _agent_name_from_cwd()
    if not name:
        click.echo("Error: no agent name given and no .agent.json in current directory.")
        raise SystemExit(1)
    api.delete(f"/agents/{name}/mute")
    click.echo(f"{name}: unmuted.")


@click.command("widget")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def widget(name):
    """Reopen the agent widget on the current Space."""
    if not name:
        name = _agent_name_from_cwd()
    if not name:
        click.echo("Error: no agent name given and no .agent.json in current directory.")
        raise SystemExit(1)
    subprocess.run(["open", f"localagentsociety://{name}?action=reopen"], check=False)
    click.echo(f"Widget reopened for {name}.")
