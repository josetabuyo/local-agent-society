import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
import click
from cli import api
from cli.commands import complete_agent_names, complete_voice_names
from cli.commands._agent_common import infer_locale, resolve_agent_name


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
    locale = infer_locale(chosen_voice)

    # Write .agent.json
    agent_data = {
        "name": name,
        "voice": chosen_voice,
        "locale": locale,
        "pronunciation": name,
        "created": str(datetime.date.today()),
    }
    try:
        agent_file.write_text(json.dumps(agent_data, indent=2, ensure_ascii=False))
    except OSError as exc:
        click.echo(f"Error: could not write {agent_file}: {exc}")
        raise SystemExit(1)
    click.echo(f"Created {agent_file}")

    # Register with backend
    api.post("/agents", {
        "name": name,
        "voice": chosen_voice,
        "path": str(cwd),
    })
    click.echo(f"Registered '{name}' with backend.")

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
        "locale": info.get("locale") or infer_locale(voice),
        "pronunciation": info.get("pronunciation") or name,
        "created": info.get("registered_at", "")[:10],
    }
    try:
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except OSError as exc:
        click.echo(f"Error: could not write {target}: {exc}")
        raise SystemExit(1)
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
    name = resolve_agent_name(name)
    if not yes:
        click.confirm(f"Unregister '{name}' from the backend?", abort=True)
    api.delete(f"/agents/{name}")
    click.echo(f"Agent '{name}' unregistered.")


@agent.command("focus")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def focus(name):
    """Bring the agent's iTerm2 window to the front."""
    name = resolve_agent_name(name)
    result = api.post(f"/agents/{name}/focus", {})
    focused = result.get("focused", False)
    click.echo(f"{name}: {'focused' if focused else 'session not found'}")


@agent.command("inject")
@click.argument("name", shell_complete=complete_agent_names)
@click.argument("message")
@click.option("--from", "from_agent", default=None, help="Sender name shown to the recipient")
def inject(name, message, from_agent):
    """Send a message to another agent via vortexia (las/agent/<name>/inbox)."""
    payload = {
        "message": message,
        "source": "agent" if from_agent else "external",
    }
    if from_agent:
        payload["from_agent"] = from_agent
    result = api.post(f"/agents/{name}/inject", payload)
    injected = result.get("injected", False)
    if injected:
        status = "sent via vortexia"
    else:
        status = "vortexia unreachable — not delivered (is `vortexia start` running?)"
    click.echo(f"{name}: {status}")


@agent.command("register")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def register(name):
    """Announce presence on vortexia (las/agent/<name>/presence, retained online).

    Called by the /las-agent skill at the start of a session. One-shot —
    doesn't hold a live MQTT connection open, so it's safe to run from a
    short-lived CLI process.
    """
    name = resolve_agent_name(name)
    result = api.post(f"/agents/{name}/vortexia/register", {})
    status = "online" if result.get("registered") else "vortexia unreachable — presence not set"
    click.echo(f"{name}: {status}")


@agent.command("poll")
@click.argument("name", required=False, shell_complete=complete_agent_names)
@click.option("--timeout", default=2.0, type=float, help="Seconds to wait for pending inbox messages.")
def poll(name, timeout):
    """Drain this agent's vortexia inbox and print any pending messages.

    Called by the /las-agent skill at the start of a session — replaces the
    old live-TTY injection model, which didn't need polling because the
    backend typed straight into an already-open terminal.
    """
    name = resolve_agent_name(name)
    result = api.get(f"/agents/{name}/vortexia/poll?timeout={timeout}")
    messages = result.get("messages", [])
    if not messages:
        click.echo(f"{name}: no pending messages.")
        return
    click.echo(f"{name}: {len(messages)} pending message(s):")
    for m in messages:
        sender = m.get("from", "?")
        text   = m.get("text", "")
        click.echo(f"  [{sender}]: {text}")


@agent.command("listen")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def listen(name):
    """Stay connected and print each inbox message the INSTANT it arrives.

    `las agent poll` only catches whatever happens to be waiting at the
    moment you run it — good for "what did I miss since last time" at
    session start, useless for hearing something the moment it's said.
    `listen` is the live counterpart: it holds an MQTT connection open and
    prints one JSON line per message as it arrives, forever, until killed.

    This is meant to run under something that reacts to each printed line —
    Claude Code's Monitor tool is the intended consumer (see
    .claude/skills/las-agent/SKILL.md, which wires this up automatically at
    session start so live delivery is standard behavior for every agent,
    not something improvised per-conversation).

    Each message is consumed on receipt (its retained flag is cleared, same
    as `las agent poll` does) — while `listen` is running, it IS the live
    delivery path, so a later `poll` won't see the same message again.
    """
    name = resolve_agent_name(name)
    ports = api.get("/ports") or {}
    mqtt_port = next((info.get("port") for info in ports.values() if info.get("app") == "vortexia-mqtt"), None)
    if mqtt_port is None:
        click.echo("vortexia unreachable — is `vortexia start` running?", err=True)
        sys.exit(1)

    # Reuse the backend's vendored vortexia client (topic naming, envelope
    # shape) instead of duplicating that logic here.
    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    sys.path.insert(0, str(backend_dir))
    import vortexia_client as vx  # noqa: E402  (path must be set first)
    import paho.mqtt.client as mqtt  # noqa: E402

    topic = vx.inbox_topic(name)
    client = mqtt.Client(client_id=f"las-listen-{name}-{os.getpid()}", protocol=mqtt.MQTTv311)

    def on_connect(c, userdata, flags, rc):
        c.subscribe(topic, qos=1)

    def on_message(c, userdata, msg):
        try:
            envelope = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        click.echo(json.dumps(envelope))
        sys.stdout.flush()
        # Consume: clear the retained flag so a later `poll` doesn't see
        # this same message again — this listener IS the delivery.
        c.publish(topic, payload=None, qos=1, retain=True)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("localhost", mqtt_port, keepalive=30)
    client.loop_forever()


@agent.command("rename")
@click.argument("old_name", required=False, shell_complete=complete_agent_names)
@click.argument("new_name")
@click.option("--pronunciation", default=None, help="Override pronunciation (defaults to new name).")
def rename(old_name, new_name, pronunciation):
    """Rename an agent in the backend registry and update .agent.json."""
    cwd_agent_file = Path.cwd() / ".agent.json"

    old_name = resolve_agent_name(old_name)

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
    """Send a '/clear' message to the agent's vortexia inbox.

    NOTE: this no longer types /clear into a live terminal (that required
    AppleScript/TTY injection, now removed). It only actually clears
    anything if something is polling the agent's inbox and interprets a
    literal '/clear' message as a command — today that's just the
    /las-agent skill surfacing it as a regular message.
    """
    name = resolve_agent_name(name)
    result = api.post(f"/agents/{name}/inject", {"message": "/clear", "source": "raw"})
    injected = result.get("injected", False)
    status = "sent via vortexia" if injected else "vortexia unreachable — not delivered"
    click.echo(f"{name}: {status}")


@agent.command("mute")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def mute(name):
    """Mute an agent's TTS voice."""
    name = resolve_agent_name(name)
    api.post(f"/agents/{name}/mute", {})
    click.echo(f"{name}: muted.")


@agent.command("unmute")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def unmute(name):
    """Unmute an agent's TTS voice."""
    name = resolve_agent_name(name)
    api.delete(f"/agents/{name}/mute")
    click.echo(f"{name}: unmuted.")


@click.command("widget")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def widget(name):
    """Reopen the agent widget on the current Space."""
    name = resolve_agent_name(name)
    subprocess.run(["open", f"localagentsociety://{name}?action=reopen"], check=False)
    click.echo(f"Widget reopened for {name}.")


@click.command("widgets")
def widgets_all():
    """Reopen all agent widgets on the current Space."""
    data = api.get("/agents")
    if not data:
        click.echo("No agents registered.")
        return
    for name in data:
        subprocess.run(["open", f"localagentsociety://{name}?action=reopen"], check=False)
        click.echo(f"  ↺ {name}")


@click.command("link")
@click.option("--agent", "agent_name", default=None,
              help="Agent name to link. Defaults to agent in current directory.")
@click.option("--tty", "tty_override", default=None,
              help="TTY device to link (e.g. /dev/ttys004). Auto-detected if omitted.")
def link(agent_name, tty_override):
    """Link a terminal session to a widget (drag the scope button or run manually)."""
    agent_name = resolve_agent_name(agent_name, err=True)

    tty = tty_override
    if not tty:
        # Try stdin/stdout/stderr first (works in regular shells)
        for fd in (0, 1, 2):
            try:
                tty = os.ttyname(fd)
                break
            except OSError:
                pass
    if not tty:
        # Walk up the process tree until we find a process with a real TTY.
        # This works for Claude Code terminals where stdin is redirected but
        # an ancestor process (Claude Code itself) owns the controlling terminal.
        pid = os.getpid()
        for _ in range(10):
            try:
                out = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "tty=,ppid="],
                    capture_output=True, text=True, timeout=2,
                ).stdout.split()
                t = out[0] if out else "??"
                if t and t != "??":
                    tty = f"/dev/{t}" if not t.startswith("/") else t
                    break
                pid = int(out[1]) if len(out) > 1 else 0
                if pid <= 1:
                    break
            except Exception:
                break
    if not tty:
        click.echo("Error: could not determine TTY.", err=True)
        raise SystemExit(1)

    try:
        result = api.post(f"/agents/{agent_name}/pin-tty", {"tty": tty})
        if result.get("ok"):
            click.echo(f"✓ Terminal {tty} linked to {agent_name}")
        else:
            click.echo(f"Backend error: {result}", err=True)
    except Exception as e:
        click.echo(f"Error contacting backend: {e}", err=True)
        raise SystemExit(1)
