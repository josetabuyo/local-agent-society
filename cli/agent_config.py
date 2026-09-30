"""`.las-agent.json` — the agent-owned config file, and its `sessions` section.

Shared by the CLI (`las agent new`, `las agent target`) and the backend
(`GET/PATCH /agents/{name}/config`, session routing) so the schema lives in
exactly one place. See docs/adr/0005-nested-mailboxes.md.

An agent's connected runtimes (a Claude, a Codex, a plain shell — its
*sessions*, docs/adr/0004) are its children queues. Where an inbound message
goes when the sender does not say, and how each child is described to a
router, is the agent's own business, so it is declared here, in its file:

    "sessions": {
      "target": "default" | "all" | "<runtime>" | "<sid>",
      "cc_default": false,
      "runtimes": {
        "shell": {"intelligent": false, "accepts": ["command"], "scope": "..."},
        ...
      }
    }

- `target` — where a plain send (and the widget mic) lands: the last-used
  session (`default`, via the agent mailbox), every connected session
  (`all`), or one runtime / session id. A configured target that is not
  connected falls back to the agent mailbox, so nothing is ever lost.
- `cc_default` — when the message went somewhere other than the default
  session, also hand the default (usually the intelligent one) a
  for-the-record copy (`kind: "cc"`), so it keeps track of what the human
  told the shell.
- `runtimes` — one descriptor per runtime kind: whether it understands
  natural language, which message kinds it accepts, and a one-line scope a
  router can match on — the same idea as the agent's own scope ladder
  (docs/adr/0001), one level down.
"""
import copy
import json
from pathlib import Path

TARGET_DEFAULT = "default"
TARGET_ALL = "all"

KIND_MESSAGE = "message"
KIND_COMMAND = "command"

DEFAULT_RUNTIMES = {
    "claude": {
        "intelligent": True,
        "accepts": [KIND_MESSAGE, KIND_COMMAND],
        "scope": "Claude Code session: natural language and commands, acts and reports back",
    },
    "codex": {
        "intelligent": True,
        "accepts": [KIND_MESSAGE, KIND_COMMAND],
        "scope": "Codex TUI: natural-language coding tasks typed into it",
    },
    "shell": {
        "intelligent": False,
        "accepts": [KIND_COMMAND],
        "scope": "plain shell: literal commands only, prose is printed and never run",
    },
}


def default_sessions_config() -> dict:
    return {"target": TARGET_DEFAULT, "cc_default": False, "runtimes": copy.deepcopy(DEFAULT_RUNTIMES)}


def sessions_config(config: dict | None) -> dict:
    """The effective `sessions` section of `config`: defaults filled in, runtimes merged per key."""
    merged = default_sessions_config()
    declared = (config or {}).get("sessions") or {}
    if isinstance(declared.get("target"), str) and declared["target"]:
        merged["target"] = declared["target"]
    merged["cc_default"] = bool(declared.get("cc_default", False))
    for runtime, descriptor in (declared.get("runtimes") or {}).items():
        if isinstance(descriptor, dict):
            merged["runtimes"][runtime] = {**merged["runtimes"].get(runtime, {}), **descriptor}
    return merged


def runtime_descriptor(config: dict | None, runtime: str) -> dict:
    """{intelligent, accepts, scope} for one runtime kind — an unknown runtime is assumed intelligent, accepting everything."""
    known = sessions_config(config)["runtimes"].get(runtime)
    return dict(known) if known else {"intelligent": True, "accepts": [KIND_MESSAGE, KIND_COMMAND], "scope": ""}


def merge_config_patch(config: dict, patch: dict) -> dict:
    """`config` with `patch` applied: top-level keys replaced, `sessions` merged one level deep (its `runtimes` per key)."""
    result = copy.deepcopy(config)
    for key, value in patch.items():
        if key == "sessions" and isinstance(value, dict):
            current = dict(result.get("sessions") or {})
            for skey, svalue in value.items():
                if skey == "runtimes" and isinstance(svalue, dict):
                    runtimes = dict(current.get("runtimes") or {})
                    for runtime, descriptor in svalue.items():
                        runtimes[runtime] = {**(runtimes.get(runtime) or {}), **descriptor} if isinstance(descriptor, dict) else descriptor
                    current["runtimes"] = runtimes
                else:
                    current[skey] = svalue
            result["sessions"] = current
        else:
            result[key] = value
    return result


def read_agent_config(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_agent_config(path: Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
