import requests

_BASE = "http://localhost:8700"


def _safe_get(path):
    """Fetch from backend without sys.exit — safe for use in shell_complete callbacks."""
    try:
        r = requests.get(f"{_BASE}{path}", timeout=2)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def complete_agent_names(ctx, param, incomplete):
    from click.shell_completion import CompletionItem
    agents = _safe_get("/agents")
    return [CompletionItem(n) for n in agents if n.lower().startswith(incomplete.lower())]


def complete_voice_names(ctx, param, incomplete):
    from click.shell_completion import CompletionItem
    data = _safe_get("/voices")
    voices = data.get("voices", [])
    items = []
    for v in voices:
        name = v["name"] if isinstance(v, dict) else v
        if name.lower().startswith(incomplete.lower()):
            items.append(CompletionItem(name))
    return items
