import os
from pathlib import Path
import click


def _detect_shell():
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return "zsh"
    if "bash" in shell:
        return "bash"
    if "fish" in shell:
        return "fish"
    return None


def _completion_line(shell):
    if shell == "zsh":
        return 'eval "$(_LAS_COMPLETE=zsh_source las)"'
    if shell == "bash":
        return 'eval "$(_LAS_COMPLETE=bash_source las)"'
    if shell == "fish":
        return 'eval (env _LAS_COMPLETE=fish_source las)'
    return None


def _shell_config(shell):
    home = Path.home()
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "bash":
        if (home / ".bash_profile").exists():
            return home / ".bash_profile"
        return home / ".bashrc"
    if shell == "fish":
        cfg = home / ".config" / "fish" / "config.fish"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        return cfg
    return None


@click.command("completion")
@click.option("--shell", "shell_name", default=None,
              type=click.Choice(["zsh", "bash", "fish"]),
              help="Shell type (auto-detected if omitted).")
@click.option("--install", is_flag=True,
              help="Append the completion hook to your shell config.")
def completion(shell_name, install):
    """Set up shell tab completion for las.

    Without --install, prints the line you need to add.
    With --install, appends it to your shell config automatically.
    """
    shell = shell_name or _detect_shell()
    if not shell:
        click.echo("Could not detect shell. Use --shell zsh|bash|fish.", err=True)
        raise SystemExit(1)

    line = _completion_line(shell)
    config = _shell_config(shell)

    if install:
        if not config:
            click.echo(f"Unknown config file for {shell}.", err=True)
            raise SystemExit(1)
        if config.exists() and line in config.read_text():
            click.echo(f"Already installed in {config}")
            return
        with config.open("a") as f:
            f.write(f"\n# las tab completion\n{line}\n")
        click.echo(f"Installed in {config}")
        click.echo(f"Restart your shell or run:  source {config}")
    else:
        click.echo(f"# Add to {config or '~/.zshrc'}:")
        click.echo(line)
        click.echo()
        click.echo("Or run:  las completion --install")
