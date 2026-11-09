"""`las voices` — the Kokoro voices every agent speaks with (cli/voice_catalog.py).

An id seen here is what `tts_voice` takes in .las-agent.json, on this machine
or a friend's: the catalogue is the same everywhere.
"""
from urllib.parse import quote

import click

from cli import api
from cli.commands import complete_voice_names

_GENDER = {"female": "♀", "male": "♂", "mixed": "⚥"}
_LANG = {"es": "Spanish", "en": "English"}


def _who(agents: list) -> str:
    return ", ".join(a["agent"] + ("" if a["how"] == "pinned" else " (hash)") + (" · inactive" if a.get("inactive") else "")
                     for a in agents)


@click.group()
def voices():
    """The Kokoro voices agents speak with — ids for `tts_voice` in .las-agent.json."""


@voices.command("list")
@click.option("--lang", default=None, help="Only one language: es, en.")
@click.option("--gender", type=click.Choice(["female", "male", "mixed"]), default=None)
@click.option("--free", is_flag=True, help="Only voices no agent here speaks with.")
@click.option("--used", is_flag=True, help="Only voices some agent here speaks with.")
def list_voices(lang, gender, free, used):
    """Every voice, by language, with the agents on this machine that speak with it.

    \b
      las voices list                      # all, and who uses each
      las voices list --lang es --gender male --free
    Pin one: "tts_voice": "<id>" in the agent's .las-agent.json (then `las agent sync`).
    """
    rows = api.get("/voices").get("voices", [])
    current = None
    for v in rows:
        code = v["lang"].split("-")[0].lower()
        if (lang and code != lang.lower()) or (gender and v["gender"] != gender) \
                or (free and v["agents"]) or (used and not v["agents"]):
            continue
        if code != current:
            current = code
            click.echo(f"\n{_LANG.get(code, code)}")
        click.echo(f"  {_GENDER.get(v['gender'], '?')} {v['name']:<30} {_who(v['agents'])}")
    click.echo("")


@voices.command("info")
@click.argument("name", shell_complete=complete_voice_names)
def voice_info(name):
    """One voice: language, gender, and who speaks with it."""
    v = api.get(f"/voices/{quote(name, safe='')}")
    click.echo(f"{v['name']}  ·  {v['lang']}  ·  {v['gender']}" + ("  ·  pin only" if v.get("pin_only") else ""))
    click.echo(f"  used by: {_who(v['agents']) or 'nobody'}")


@voices.command("random")
@click.option("--locale", default="es-MX", show_default=True)
@click.option("--gender", type=click.Choice(["female", "male", "mixed"]), default=None)
def random_voice(locale, gender):
    """A voice of LOCALE's language no agent here speaks with yet."""
    query = f"/voices/random?locale={quote(locale)}" + (f"&gender={gender}" if gender else "")
    click.echo(api.get(query).get("voice", ""))
