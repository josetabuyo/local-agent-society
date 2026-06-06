import subprocess
import click
from pathlib import Path

# Resolve from cli/commands/boarding.py → project root → docs/boarding.html
_BOARDING = (Path(__file__).parent.parent.parent / "docs" / "boarding.html").resolve()


@click.command("boarding")
@click.option("--open", "open_browser", is_flag=True, help="Open in the default browser.")
def boarding(open_browser: bool):
    """Print the path to the boarding page.

    \b
    Examples:
      las boarding           # print path
      las boarding --open    # open in browser
      open $(las boarding)   # shell one-liner
    """
    if not _BOARDING.exists():
        click.echo(f"boarding.html not found at {_BOARDING}", err=True)
        raise SystemExit(1)
    click.echo(str(_BOARDING))
    if open_browser:
        subprocess.run(["open", f"file://{_BOARDING}"], check=False)
