"""`las vocab` — the dictation vocabulary (cli/vocabulary.py)."""
import click

from cli import api
from cli import vocabulary as vocab


@click.group()
def vocab_cmd():
    """Words dictation keeps mishearing, put back right (agent names, dev terms, yours)."""


@vocab_cmd.command("add")
@click.argument("entry")
def add(entry):
    """Add a term ("Supabase") or an explicit spelling ("supabeis => Supabase")."""
    vocab.add_entry(entry)
    click.echo(f"added to {vocab.USER_FILE}: {entry}")


@vocab_cmd.command("test")
@click.argument("text")
def test(text):
    """Show what a dictated TEXT becomes (through the backend, with every agent's name)."""
    res = api.post("/dictation/fix", {"text": text})
    click.echo(res["text"] if res.get("changed") else f"(unchanged) {res['text']}")


@vocab_cmd.command("list")
def list_():
    """Your own entries (~/.las/vocabulary.txt); built-ins live in cli/vocabulary.py."""
    terms, heard = vocab.load_user_file()
    if not terms and not heard:
        click.echo(f"no entries yet — `las vocab add \"term\"` or \"heard => term\" ({vocab.USER_FILE})")
    for t in terms:
        click.echo(t)
    for h, t in heard.items():
        click.echo(f"{h} => {t}")
