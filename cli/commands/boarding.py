import subprocess
import click
from pathlib import Path

# Resolve from cli/commands/boarding.py → project root → docs/boarding.html
_BOARDING = (Path(__file__).parent.parent.parent / "docs" / "boarding.html").resolve()


@click.command("boarding")
@click.option("--print", "print_only", is_flag=True, help="Print the file path instead of opening it.")
def boarding(print_only: bool):
    """Open the Local Agent Society boarding page.

    \b
    Examples:
      las boarding           # open in browser
      las boarding --print   # print path (for scripting)
      open $(las boarding --print)
    """
    if not _BOARDING.exists():
        click.echo(f"boarding.html not found at {_BOARDING}", err=True)
        raise SystemExit(1)
    if print_only:
        click.echo(str(_BOARDING))
        return
    subprocess.run(["open", str(_BOARDING)], check=False)
