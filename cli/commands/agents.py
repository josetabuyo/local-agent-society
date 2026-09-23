import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
import click
from cli import api
from cli.commands import complete_agent_names, complete_voice_names
from cli.commands._agent_common import infer_locale, resolve_agent_name
from cli.path_utils import AGENT_CONFIG_FILENAME, agent_config_path
from cli.hierarchy import tree_lines


@click.group()
def agent():
    """Manage agents.

    Cross-machine messaging already exists — don't rebuild it. `send --to
    "Name@env"` reaches an agent on a different Mac via vortex-relay (LAN
    direct when possible, falling back to a Nostr relay). See `las agent
    send --help` and the /las-agent skill before assuming this needs a
    new mechanism.
    """


@click.command("agents")
@click.option("--inactive", "inactive_only", is_flag=True, help="Show only inactive (put-away) agents.")
@click.option("--active", "active_only", is_flag=True, help="Show only active agents (default: shows all).")
@click.option("--tree", "as_tree", is_flag=True, help="Render the folder-derived hierarchy (parents above their subordinates).")
def agents_list(inactive_only, active_only, as_tree):
    """List all registered agents."""
    data = api.get("/agents")
    if not data:
        click.echo("No agents registered.")
        return
    if as_tree:
        for line in tree_lines(data, marker=lambda n, i: "  (inactive)" if i.get("inactive") else ""):
            click.echo(line)
        return
    if inactive_only:
        data = {n: i for n, i in data.items() if i.get("inactive")}
    elif active_only:
        data = {n: i for n, i in data.items() if not i.get("inactive")}
    if not data:
        click.echo("No matching agents.")
        return
    click.echo(f"{'Name':<20} {'Voice':<25} {'Status':<10} {'Path'}")
    click.echo("-" * 80)
    for name, info in data.items():
        status = "inactive" if info.get("inactive") else "active"
        click.echo(f"{name:<20} {info.get('voice','?'):<25} {status:<10} {info.get('path','?')}")


@agent.command("new")
@click.argument("name")
@click.option("--voice", default=None, shell_complete=complete_voice_names, help="TTS voice name. Auto-assigned if omitted.")
@click.option("--dir", "target_dir", default=None,
              help="Directory for the agent (default: current directory).")
def new(name, voice, target_dir):
    """Create a new agent: writes .las-agent.json, registers with backend, launches widget."""
    cwd = Path(target_dir).resolve() if target_dir else Path.cwd()

    # Ensure target dir exists
    cwd.mkdir(parents=True, exist_ok=True)

    # Guard: don't overwrite an existing agent (new or legacy filename)
    existing_file = agent_config_path(cwd)
    if existing_file:
        existing = json.loads(existing_file.read_text()).get("name", "?")
        click.echo(f"Error: {existing_file} already exists (agent '{existing}'). "
                   "Use `las agent rename` or delete it first.")
        raise SystemExit(1)
    agent_file = cwd / AGENT_CONFIG_FILENAME

    # Pick voice
    if voice:
        chosen_voice = voice
    else:
        data = api.get("/voices/random")
        chosen_voice = data.get("voice") or data.get("name", "Samantha")

    # Resolve locale from voice
    locale = infer_locale(chosen_voice)

    # Write .las-agent.json
    agent_data = {
        "name": name,
        "voice": chosen_voice,
        "locale": locale,
        "pronunciation": name,
        "created": str(datetime.date.today()),
        # A soft target for the LENGTH of THIS agent's own spoken
        # summary/acknowledge responses (report/closing lines) — never a hard
        # truncation, and never applied to text the agent RECEIVES (mic
        # dictation, other agents' messages). Named response_length_hint,
        # not *_limit or *_max, precisely so it reads as a suggestion.
        "response_length_hint": 40,
        # Empty by design — filled in over time, and meant to eventually back
        # a vortexia intent-filter broadcast (who this agent is, what it
        # offers, what it needs).
        "short_description": "",
        "long_description": "",
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
    subprocess.run(["open", f"localagentsociety://{quote(name, safe='')}?action=reopen"], check=False)
    click.echo(f"Widget launched.")

    # Announce
    lang = locale.split("-")[0]
    greeting = f"Hello, I am {name}, ready." if lang != "es" else f"Hola, soy {name}, listo."
    api.post("/queue/speak", {"text": greeting, "voice": chosen_voice, "name": name})

    click.echo(f"\nAgent '{name}' created — voice: {chosen_voice}, locale: {locale}")


@agent.command("restore")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def restore(name):
    """Restore .las-agent.json from backend registry (use if accidentally deleted)."""
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

    target = cwd / AGENT_CONFIG_FILENAME
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
    click.echo(f"Restored {AGENT_CONFIG_FILENAME} for '{name}' (voice: {data['voice']}).")


@agent.command("sync")
def sync():
    """Sync the agent config in the current directory to the backend registry."""
    p = agent_config_path(Path.cwd())
    if not p:
        click.echo(f"Error: no {AGENT_CONFIG_FILENAME} in current directory.")
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


@agent.command("send")
@click.argument("message")
@click.option("--to", default=None, help="Exact agent name, optionally \"Name@env\" for a specific environment (cross-machine)")
@click.option("--scope", default=None, help="Free-text scope/intent instead of an exact name — broadcasts to whoever matches, possibly more than one agent")
@click.option("--from", "from_agent", default=None, help="Sender name shown to the recipient(s)")
@click.option("--children", "to_children", is_flag=True,
              help="Deliver to every subordinate of --to (agents whose folder sits under its folder) instead of to --to itself")
@click.option("--deep", is_flag=True, help="With --children: the whole subtree, not only direct subordinates")
def send(message, to, scope, from_agent, to_children, deep):
    """Generic send: point-to-point (--to) or scope broadcast (--scope), local or cross-machine.

    Replaces `inject`'s exact-name-only, single-machine model with one
    primitive that also reaches another environment (a different Mac,
    via vortex-relay — see vortexia/docs/vortex-relay-poc.md):

    \b
      las agent send --to System "..."            # local, or vortex-relayed if not found locally
      las agent send --to "System@uy-mac" "..."    # explicit, disambiguates a name collision
      las agent send --scope "facturacion, pagos" "..."   # broadcast; 0, 1, or several may reply
      las agent send --to RelayRobotics --children "..."  # every subordinate of RelayRobotics (see `las agent children`)

    `inject` still works unchanged for existing scripts/skills — this is
    the new generic entry point going forward, not a replacement in place.
    """
    if bool(to) == bool(scope):
        raise click.UsageError("exactly one of --to or --scope is required")
    if (to_children or deep) and not to:
        raise click.UsageError("--children/--deep need --to <ParentAgent>")

    payload = {"message": message, "source": "agent" if from_agent else "external"}
    if from_agent:
        payload["from_agent"] = from_agent

    if to_children:
        # Hierarchy is folder-derived (cli/hierarchy.py) — ask the backend,
        # which owns the registry, then fan out one point-to-point send per
        # subordinate so each one lands in its own vortexia inbox.
        info = api.get(f"/agents/{quote(to, safe='')}/hierarchy?deep={'true' if deep else 'false'}")
        targets = [c["name"] for c in info.get("children", [])]
        if not targets:
            click.echo(f"{to}: no subordinates" + (" (try --deep)" if not deep else ""))
            return
        failures = 0
        for target in targets:
            result = api.post("/agents/send", {**payload, "to": target})
            ok = result.get("injected", False)
            failures += 0 if ok else 1
            click.echo(f"{target}: {'sent via vortexia' if ok else 'not delivered'}")
        click.echo(f"{to}: {len(targets) - failures}/{len(targets)} subordinates reached")
        if failures:
            raise SystemExit(1)
        return

    if to:
        payload["to"] = to
    else:
        payload["scope"] = scope

    result = api.post("/agents/send", payload)
    injected = result.get("injected", False)
    mode = result.get("mode", "?")
    relayed = result.get("relayed", False)
    target = to or f'scope "{scope}"'
    if injected:
        status = f"sent via vortexia ({mode}{', vortex-relay' if relayed else ''})"
    else:
        status = "vortexia unreachable — not delivered (is `vortexia start` running?)"
    click.echo(f"{target}: {status}")


@agent.command("children")
@click.argument("name", required=False, shell_complete=complete_agent_names)
@click.option("--deep", is_flag=True, help="Whole subtree, not only direct subordinates")
def children(name, deep):
    """List the subordinates of an agent (default: the agent in the cwd).

    Hierarchy is read from the folders, never declared: any registered agent
    whose path sits under this agent's path is a subordinate. Create one with
    `las agent new NAME --dir <repo>` from inside the parent's folder.
    """
    name = resolve_agent_name(name)
    info = api.get(f"/agents/{quote(name, safe='')}/hierarchy?deep={'true' if deep else 'false'}")
    kids = info.get("children", [])
    if not kids:
        click.echo(f"{name}: no subordinates" + ("" if deep else " (try --deep)"))
        return
    for c in kids:
        click.echo(f"{c['name']:<20} {c.get('voice') or '?':<25} {c.get('path', '?')}")


@agent.command("parent")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def parent(name):
    """Print the agent this one reports to (nearest registered ancestor folder), if any."""
    name = resolve_agent_name(name)
    info = api.get(f"/agents/{quote(name, safe='')}/hierarchy")
    click.echo(info.get("parent") or f"{name}: top-level (no parent agent)")


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
    """Drain this agent's mailbox and print everything that was queued.

    Called by the /las-agent skill at the start of a session. The broker
    keeps a persistent mailbox per agent (vortexia/PROTOCOL.md "Mailboxes"):
    every message sent while no session was open is waiting here, in order.
    Prints "no pending messages" without draining when a live `las agent
    listen` already holds the mailbox — that listener is the delivery path.
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

    It connects as the agent's MAILBOX consumer (client id las-agent-<name>,
    persistent session — see vortexia/PROTOCOL.md "Mailboxes"): on connect
    the broker hands over everything queued while nobody was listening, in
    order, then live traffic; each message is consumed by being acknowledged
    (QoS 1), nothing to clear. While `listen` runs it IS the delivery path —
    `las agent poll` sees the session is held and stands down. Only one
    consumer can hold the session: if another connection takes it over, this
    process exits (exit 2) instead of reconnecting and fighting it. The
    /las-agent skill's "purge before Monitor" step exists for exactly that.

    Mechanically (and silently — no TTS) answers the mic self-test sentinel
    (see widget.js's MIC_SELFTEST_PING and runMicSelfTest) the instant it
    arrives, by publishing a "mic-selftest-pong" envelope straight back on
    this same inbox topic — no LLM session needs to notice or act for the
    double-click self-test to succeed. This is deliberately decoupled: the
    widget's self-test only needs to know the mic → vortexia → a live
    terminal-side listener pipe is intact, which this process alone already
    proves just by being connected and running; it says nothing about
    whether an actual Claude Code session is attached and paying attention,
    so it must not speak out loud as if a real reply happened. Whether an
    LLM is attached and chooses to also answer with an audible "OK" (see the
    `las-agent` skill's "Ping de self-test" section) is a separate, optional
    layer — the widget reacts to whichever confirmation (silent pong or
    spoken "OK") arrives first.
    """
    name = resolve_agent_name(name)
    ports = api.get("/ports") or {}

    # Reuse the backend's vendored vortexia client (topic naming, envelope
    # shape, broker port resolution) instead of duplicating that logic here.
    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    sys.path.insert(0, str(backend_dir))
    import vortexia_client as vx  # noqa: E402  (path must be set first)
    import paho.mqtt.client as mqtt  # noqa: E402

    # Same precedence as backend/main.py's _vortexia_mqtt_port: the live
    # broker's vortexia.port.json beats the registry, whose claim can be
    # stale after a reboot race (see resolve_mqtt_port's docstring).
    mqtt_port = vx.resolve_mqtt_port(ports, default=None)
    if mqtt_port is None:
        click.echo("vortexia unreachable — is `vortexia start` running?", err=True)
        sys.exit(1)

    topic = vx.inbox_topic(name)
    # The mailbox consumer: fixed client id + persistent session. The broker
    # restores the inbox subscription on reconnect (and creates it on the
    # first publish to the inbox), so subscribe only when it reports no
    # session present — re-subscribing would replay a retained message some
    # pre-mailbox sender left on the topic.
    client = mqtt.Client(client_id=vx.mailbox_client_id(name), clean_session=False, protocol=mqtt.MQTTv311)

    # Must match widget.js's MIC_SELFTEST_PING exactly — no shared module
    # between the JS renderer and this CLI, so this is a deliberate literal
    # duplication (same as the las-agent skill's own copy of this string).
    MIC_SELFTEST_PING = '[las-mic-selftest] reply with just "OK" to confirm this session is listening.'

    def on_connect(c, userdata, flags, rc, *_args):
        if not vx._session_present(flags):
            c.subscribe(topic, qos=1)

    def on_disconnect(c, userdata, rc, *_args):
        # rc != 0 is an unexpected drop: broker restart, or another client
        # taking over this session (MQTT-3.1.4-2). Either way exit rather
        # than auto-reconnect — a reconnecting listener vs. a takeover would
        # kick each other forever, and the Monitor re-arms us on exit anyway.
        if rc != 0:
            click.echo(f"{name}: mailbox session lost (rc={rc}) — taken over by another listener, or broker restarted", err=True)
            os._exit(2)

    def on_message(c, userdata, msg):
        try:
            envelope = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        click.echo(json.dumps(envelope))
        sys.stdout.flush()
        # Consumed by the QoS 1 ack paho sends when this handler returns —
        # no retained-flag clearing, the mailbox is a queue now.
        if envelope.get("text") == MIC_SELFTEST_PING:
            # Silent, direct MQTT pong — deliberately NOT /queue/speak. This
            # confirms only that the plumbing (mic -> vortexia -> a live
            # `listen` process) works; not retained, since a stale "yes I was
            # here" from minutes ago would be a false confirmation of "right
            # now". See widget.js's onVortexiaMessage for the matching kind
            # check (no TTS, no chat bubble).
            pong = {
                "from": name,
                "to": name,
                "source": "system",
                "kind": "mic-selftest-pong",
                "text": "OK",
                "ts": int(time.time() * 1000),
            }
            c.publish(topic, payload=json.dumps(pong), qos=1, retain=False)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    try:
        client.connect("localhost", mqtt_port, keepalive=30)
    except OSError as exc:
        # A known port with nobody on it (broker died, stale port file) must
        # still exit cleanly — this runs under Claude Code's Monitor tool,
        # where a traceback or a hang would stall session start.
        click.echo(f"vortexia unreachable on :{mqtt_port} ({exc}) — is `vortexia start` running?", err=True)
        sys.exit(1)
    client.loop_forever()


@agent.command("rename")
@click.argument("old_name", required=False, shell_complete=complete_agent_names)
@click.argument("new_name")
@click.option("--pronunciation", default=None, help="Override pronunciation (defaults to new name).")
def rename(old_name, new_name, pronunciation):
    """Rename an agent in the backend registry and update its agent config."""
    cwd_agent_file = agent_config_path(Path.cwd())

    old_name = resolve_agent_name(old_name)

    result = api.patch(f"/agents/{old_name}", {
        "new_name": new_name,
        **({"pronunciation": pronunciation} if pronunciation else {}),
    })
    click.echo(f"Renamed '{old_name}' → '{new_name}' in backend registry.")

    # Tell a running widget-electron app so an already-open window for
    # old_name follows the rename instead of going stale — see
    # widget-electron/main.js's handleProtocolUrl for the 'rename' action.
    # No-op (fire-and-forget, same as the other `open localagentsociety://`
    # calls in this file) if no window is open for old_name or the app isn't
    # running at all.
    subprocess.run(
        ["open", f"localagentsociety://{quote(old_name, safe='')}?action=rename&to={quote(new_name, safe='')}"],
        check=False,
    )

    if cwd_agent_file:
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
                # Opportunistically migrate the filename to the current
                # convention while we're already rewriting the file.
                new_path = cwd_agent_file.with_name(AGENT_CONFIG_FILENAME)
                new_path.write_text(json.dumps(d, indent=2, ensure_ascii=False))
                if new_path != cwd_agent_file:
                    cwd_agent_file.unlink()
                click.echo(f"Updated {AGENT_CONFIG_FILENAME} (name, pronunciation).")
        except Exception as exc:
            click.echo(f"Warning: could not update agent config — {exc}")


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


@agent.command("deactivate")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def deactivate(name):
    """Mark an agent inactive and close its widget (does not touch its Claude Code session)."""
    name = resolve_agent_name(name)
    api.post(f"/agents/{name}/inactive", {})
    subprocess.run(["open", f"localagentsociety://{quote(name, safe='')}?action=close"], check=False)
    click.echo(f"{name}: inactive.")


@agent.command("activate")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def activate(name):
    """Mark an agent active again (see `las agents --inactive` to find one)."""
    name = resolve_agent_name(name)
    api.delete(f"/agents/{name}/inactive")
    click.echo(f"{name}: active.")


@agent.command("wake-enable")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def wake_enable(name):
    """Allow `las agent focus`/vortexia to wake this agent when inactive (opens a new
    iTerm2 window running `claude --dangerously-skip-permissions` in its directory)."""
    name = resolve_agent_name(name)
    api.post(f"/agents/{name}/wake-enabled", {})
    click.echo(f"{name}: wake-up via vortexia enabled.")


@agent.command("wake-disable")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def wake_disable(name):
    """Disallow waking this agent up automatically while inactive."""
    name = resolve_agent_name(name)
    api.delete(f"/agents/{name}/wake-enabled")
    click.echo(f"{name}: wake-up via vortexia disabled.")


@click.command("widget")
@click.argument("name", required=False, shell_complete=complete_agent_names)
def widget(name):
    """Reopen the agent widget on the current Space."""
    name = resolve_agent_name(name)
    subprocess.run(["open", f"localagentsociety://{quote(name, safe='')}?action=reopen"], check=False)
    # `open` on the URL scheme only asks macOS to route the request to the
    # handler app — it returns success even if that app then fails to launch
    # (e.g. a corrupted dist/ build). Poll for the actual process instead of
    # reporting success unconditionally, so a dead app is visible here rather
    # than only discovered later as "the widget isn't showing up".
    deadline = time.time() + 5
    while time.time() < deadline:
        result = subprocess.run(
            ["pgrep", "-f", "Local Agent Society.app/Contents/MacOS/Local Agent Society"],
            capture_output=True,
        )
        if result.returncode == 0:
            click.echo(f"Widget reopened for {name}.")
            return
        time.sleep(0.25)
    click.echo(
        f"Widget reopen requested for {name}, but no running process was found after 5s — "
        "the app may have failed to launch (check dist/ build)."
    )


@click.command("widgets")
def widgets_all():
    """Reopen all ACTIVE agent widgets on the current Space (inactive ones stay put away —
    use `las widget NAME` or `las agent activate NAME` for a specific one)."""
    data = api.get("/agents")
    if not data:
        click.echo("No agents registered.")
        return
    for name, info in data.items():
        if info.get("inactive"):
            continue
        subprocess.run(["open", f"localagentsociety://{quote(name, safe='')}?action=reopen"], check=False)
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
