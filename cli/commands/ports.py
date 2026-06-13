import click
from cli import api


@click.group()
def ports():
    """Manage port registry."""


@ports.command("ls")
def ports_ls():
    """List registered ports."""
    data = api.get("/ports")
    if not data:
        click.echo("No ports registered.")
        return
    click.echo(f"{'Port':<8} {'Agent':<20} {'App'}")
    click.echo("-" * 54)
    for port, info in sorted(data.items(), key=lambda x: int(x[0])):
        click.echo(f":{port:<7} {info.get('local_agent','?'):<20} {info.get('app','')}")


@ports.command("free")
@click.option("--start", default=9000, help="Range start (default 9000)")
@click.option("--end",   default=9999, help="Range end (default 9999)")
def ports_free(start, end):
    """Get a free port from the registry."""
    data = api.get(f"/ports/free?start={start}&end={end}")
    click.echo(data.get("port"))


@ports.command("claim")
@click.argument("app")
@click.option("--port", default=None, type=int, help="Desired port (omit for auto-assign)")
@click.option("--start", default=9000, help="Range start for auto-assign (default 9000)")
@click.option("--end",   default=9999, help="Range end for auto-assign (default 9999)")
def ports_claim(app, port, start, end):
    """Atomically claim a port (checks + registers in one step). Prints the port."""
    import json, sys
    from pathlib import Path
    agent_json = Path.cwd() / ".agent.json"
    agent_name = "CLI"
    if agent_json.exists():
        try:
            agent_name = json.loads(agent_json.read_text()).get("name", "CLI")
        except Exception:
            pass
    payload = {
        "app": app,
        "local_agent": agent_name,
        "path": str(Path.cwd()),
        "start": start,
        "end": end,
    }
    if port is not None:
        payload["port"] = port
    data = api.post("/ports/claim", payload)
    click.echo(data.get("port"))


@ports.command("release")
@click.argument("port", type=int)
def ports_release(port):
    """Release a registered port."""
    api.delete(f"/ports/{port}")
    click.echo(f"Port {port} released.")


@ports.command("audit")
def ports_audit():
    """Cross-check port registry against running processes. Finds violations and ghosts."""
    import subprocess, sys

    registry = api.get("/ports")

    try:
        lsof_out = subprocess.check_output(
            ["lsof", "-i", "-P"], stderr=subprocess.DEVNULL
        ).decode()
    except subprocess.CalledProcessError:
        click.echo("Error: could not run lsof.")
        sys.exit(1)

    listening = {}
    for line in lsof_out.splitlines():
        if "LISTEN" not in line:
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        proc, pid, addr = parts[0], parts[1], parts[8]
        port = addr.rsplit(":", 1)[-1]
        listening.setdefault(port, []).append((proc, pid))

    IGNORED = {
        "caddy", "ollama", "rapportd", "ControlCe", "sharingd",
        "bluetoot", "useractiv", "SCHelper", "UserEvent", "AirPlay",
    }

    ghosts, ok_ports, unregistered = [], [], []

    for port, info in sorted(registry.items(), key=lambda x: int(x[0])):
        owner = info["local_agent"]
        app = info["app"]
        procs = listening.get(port, [])
        if not procs:
            ghosts.append((port, owner, app))
        else:
            ok_ports.append((port, owner, app, procs))

    for port, procs in sorted(listening.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        if port in registry:
            continue
        for proc, pid in procs:
            if proc in IGNORED or not port.isdigit() or int(port) > 50000:
                continue
            unregistered.append((port, proc, pid))

    click.echo(f"\n{'PORT':<7} {'OWNER':<20} {'STATUS'}")
    click.echo("─" * 60)
    for port, owner, app, procs in ok_ports:
        proc_str = ", ".join(f"{p}({pid})" for p, pid in procs)
        click.echo(f":{port:<6} {owner:<20} OK  — {proc_str}")
    for port, owner, app in ghosts:
        click.echo(f":{port:<6} {owner:<20} GHOST — registered but not running")
    if unregistered:
        click.echo()
        click.echo("UNREGISTERED LISTENERS:")
        for port, proc, pid in unregistered:
            click.echo(f"  :{port:<6} {proc} pid={pid}")
    click.echo()
    click.echo(f"{len(ok_ports)} OK, {len(ghosts)} ghost(s), {len(unregistered)} unregistered")
