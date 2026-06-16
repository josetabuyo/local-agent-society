import os
import subprocess
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


def _zsh_completions_dir():
    """Return the zsh completions dir to use, preferring oh-my-zsh custom."""
    ohmyzsh_custom = Path(os.environ.get("ZSH_CUSTOM", Path.home() / ".oh-my-zsh" / "custom"))
    ohmyzsh_dir = ohmyzsh_custom / "completions"
    if (Path.home() / ".oh-my-zsh").exists():
        return ohmyzsh_dir
    return Path.home() / ".zsh" / "completions"


def _generate_script(shell):
    env = os.environ.copy()
    env[f"_LAS_COMPLETE"] = f"{shell}_source"
    result = subprocess.run(["las"], env=env, capture_output=True, text=True)
    return result.stdout


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
              help="Write the completion script and activate it.")
def completion(shell_name, install):
    """Set up shell tab completion for las.

    For zsh: writes a completion file to ~/.oh-my-zsh/custom/completions/_las
    (or ~/.zsh/completions/_las). Much more reliable than eval.

    For bash/fish: appends the eval hook to your shell config.
    """
    shell = shell_name or _detect_shell()
    if not shell:
        click.echo("Could not detect shell. Use --shell zsh|bash|fish.", err=True)
        raise SystemExit(1)

    if install:
        if shell == "zsh":
            completions_dir = _zsh_completions_dir()
            completions_dir.mkdir(parents=True, exist_ok=True)
            script = _generate_script("zsh")
            dest = completions_dir / "_las"
            dest.write_text(script)
            # Remove stale cache
            for f in Path.home().glob(".zcompdump*"):
                f.unlink()
            click.echo(f"Written: {dest}")
            click.echo("Zsh cache cleared. Restart your shell to activate.")
        else:
            config = _shell_config(shell)
            if shell == "bash":
                line = 'eval "$(_LAS_COMPLETE=bash_source las)"'
            else:
                line = 'eval (env _LAS_COMPLETE=fish_source las)'
            if config.exists() and line in config.read_text():
                click.echo(f"Already installed in {config}")
                return
            with config.open("a") as f:
                f.write(f"\n# las tab completion\n{line}\n")
            click.echo(f"Installed in {config}")
            click.echo(f"Restart your shell or run:  source {config}")
    else:
        if shell == "zsh":
            dest = _zsh_completions_dir() / "_las"
            click.echo(f"# Writes completion file to {dest}")
            click.echo("Run:  las completion --install")
        elif shell == "bash":
            click.echo('# Add to ~/.bashrc or ~/.bash_profile:')
            click.echo('eval "$(_LAS_COMPLETE=bash_source las)"')
            click.echo()
            click.echo("Or run:  las completion --install")
        elif shell == "fish":
            click.echo('# Add to ~/.config/fish/config.fish:')
            click.echo('eval (env _LAS_COMPLETE=fish_source las)')
            click.echo()
            click.echo("Or run:  las completion --install")
