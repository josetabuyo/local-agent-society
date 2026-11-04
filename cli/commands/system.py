import subprocess
import sys
from pathlib import Path
import click
from cli.update_notice import print_update_notice
from cli import api

# Root of the repo — two levels up from this file (cli/commands/system.py)
REPO = Path(__file__).parent.parent.parent


def _run_script(name, *args):
    script = REPO / name
    if not script.exists():
        click.echo(f"Error: {script} not found.")
        sys.exit(1)
    subprocess.run(["bash", str(script), *args], check=False)


@click.command()
def status():
    """Show backend status, registered agents, and ports."""
    health = api.get("/health")
    click.echo(f"Backend  : {health.get('status', 'unknown')}")

    agents = api.get("/agents")
    if agents:
        click.echo(f"\nAgents ({len(agents)}):")
        for name, info in agents.items():
            click.echo(f"  {name:<20} voice={info.get('voice','?')}  path={info.get('path','?')}")
    else:
        click.echo("\nAgents   : none registered")

    ports = api.get("/ports")
    if ports:
        click.echo(f"\nPorts ({len(ports)}):")
        for port, info in ports.items():
            click.echo(f"  :{port:<6} {info.get('local_agent','?')}")
    else:
        click.echo("\nPorts    : none registered")


@click.command("start")
def start_cmd():
    """Start the backend and tray app."""
    _run_script("start.sh")
    print_update_notice()


@click.command("stop")
def stop_cmd():
    """Stop the backend and tray app."""
    _run_script("stop.sh")


@click.command("restart")
@click.option("--force", is_flag=True, help="Restart even while a mic dictation is recording.")
def restart_cmd(force):
    """Restart the backend + widget — if a mic dictation is recording, beep and wait for it to end first."""
    _run_script("restart-widget.sh", *(["--force"] if force else []))


@click.command()
def logs():
    """Tail the backend log."""
    log = REPO / "backend" / "backend.log"
    if not log.exists():
        click.echo("No log file found.")
        sys.exit(1)
    try:
        subprocess.run(["tail", "-f", str(log)])
    except KeyboardInterrupt:
        pass


@click.command()
def install():
    """Install / reinstall the system (compiles widget, sets up launchd)."""
    _run_script("install.sh")


@click.command()
def uninstall():
    """Remove the system."""
    _run_script("uninstall.sh")


@click.command()
def update():
    """Pull latest, reinstall, and show what's new."""
    _run_script("update.sh")


@click.command()
@click.option("--since", "since", default=None, help="Show the changes after this commit/tag (default: before the last update).")
@click.option("-n", "count", type=int, default=None, help="Show the last N changes instead.")
def changelog(since, count):
    """What's new in Local Agent Society — the news `las update` printed.

    \b
      las changelog              # what the last `las update` brought
      las changelog -n 30        # the last 30 changes
      las changelog --since v1.0 # everything after a commit or tag
    """
    from cli import updater

    new = updater.head()
    if count:
        old = updater.git("rev-parse", f"HEAD~{count}") or updater.git("rev-list", "--max-parents=0", "HEAD")
    else:
        old = since or updater.git("rev-parse", "ORIG_HEAD") or updater.git("rev-parse", "HEAD~20")
    commits = updater.commits_between(old, new) if old and old != new else []
    if not commits:
        click.echo(f"Nothing new between {old[:7]} and {new[:7]} — try `las changelog -n 20`.")
        return
    # click strips ANSI from a non-tty; the updater already decided (Claude Code's `!` renders it).
    click.echo(f"\n  {updater.bold('What’s new')} {updater.dim(f'{old[:7]} → {new[:7]} · v{updater.version()}')}", color=updater._COLOR)
    click.echo(updater.render_changelog(commits) + "\n", color=updater._COLOR)
