"""`las route` — ask the backend's scope router who a text belongs to."""
import json

import click

from cli import api
from cli.scope_router import ROUTER_TIMEOUT_S

# The backend waits up to ROUTER_TIMEOUT_S on the model, plus a send.
ROUTE_TIMEOUT_S = ROUTER_TIMEOUT_S + 10


@click.command()
@click.argument("text")
@click.option("--deliver", is_flag=True, help="Send it to the pick when the router is confident.")
@click.option("--sessions-of", "agent", default=None, help="Pick among this agent's sessions instead of among agents.")
@click.option("--from", "from_agent", default=None, help="Sender label (default: the chosen agent itself, read as mic).")
@click.option("--json", "as_json", is_flag=True, help="Print the backend's raw decision.")
def route(text, deliver, agent, from_agent, as_json):
    """Route TEXT to the agent (or session) whose scope fits it best."""
    body = {"text": text, "level": "session" if agent else "agent", "agent": agent,
            "deliver": deliver, "from_agent": from_agent}
    res = api.post("/route", body, timeout=ROUTE_TIMEOUT_S)
    if as_json:
        click.echo(json.dumps(res, ensure_ascii=False, indent=2))
        return
    ranked = "  ".join(f"{r['name']} {r['p']:.0%}" for r in res.get("ranked", []))
    if res["decision"] == "deliver":
        sent = " — sent" if res.get("delivered") else ""
        click.echo(f"→ {res['choice']} ({res['confidence']:.0%}, margin {res['margin']:.0%}){sent}")
    else:
        click.echo(f"? pending: {res.get('reason')}")
    if ranked:
        click.echo(f"  {ranked}")
