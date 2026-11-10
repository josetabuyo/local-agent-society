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


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def sessions_config(config: dict | None) -> dict:
    """The effective `sessions` section of `config`: defaults filled in, runtimes merged per key.

    Tolerant of a hand-edited file: anything that is not the expected shape
    is ignored (a typo in one agent's file must never take a send down)."""
    merged = default_sessions_config()
    declared = _dict(_dict(config).get("sessions"))
    if isinstance(declared.get("target"), str) and declared["target"]:
        merged["target"] = declared["target"]
    merged["cc_default"] = bool(declared.get("cc_default", False))
    for runtime, descriptor in _dict(declared.get("runtimes")).items():
        if isinstance(descriptor, dict):
            merged["runtimes"][runtime] = {**merged["runtimes"].get(runtime, {}), **descriptor}
    return merged


UNKNOWN_RUNTIME = {"intelligent": True, "accepts": [KIND_MESSAGE, KIND_COMMAND], "scope": ""}


def descriptor_for(policy: dict, runtime: str) -> dict:
    """{intelligent, accepts, scope} for one runtime kind out of an effective `sessions` policy — an unknown runtime is assumed intelligent, accepting everything.

    A second Claude account (`las claude --account relay` -> runtime "claudeRelay")
    is still Claude: it inherits the `claude` descriptor unless declared itself."""
    known = policy["runtimes"].get(runtime)
    if not known and runtime.startswith("claude"):
        known = policy["runtimes"].get("claude")
    return dict(known) if known else dict(UNKNOWN_RUNTIME)


def runtime_descriptor(config: dict | None, runtime: str) -> dict:
    return descriptor_for(sessions_config(config), runtime)


# ── session titles ──────────────────────────────────────────────────────────
#
# Each connected session (a child of the agent) can carry a short title: what
# that terminal is working on right now. It is rung 0 of the scope ladder one
# level down (ADR 0001 caps rung 0 at 34 chars — a soft target, never
# truncated). The widget asks every intelligent session for one with a
# `title-request` envelope; the session answers with `las agent title`.

KIND_TITLE_REQUEST = "title-request"
TITLE_SOFT_CAP = 34
TITLE_REQUEST_PREFIX = "[las-session-title]"


def title_request_text(agent: str, sid: str) -> str:
    """The self-contained instruction handed to one session — typed verbatim into a Codex TUI, so it must stand alone."""
    return (
        f"{TITLE_REQUEST_PREFIX} sid={sid} — give this session a title: what you are working on here, "
        f"about {TITLE_SOFT_CAP} characters, in the agent's language. Set it by running "
        f"`las agent title --name {agent} --session {sid} \"<title>\"`, nothing else — no other action, no reply, no closing report."
    )


def accepts_only_commands(descriptor: dict) -> bool:
    """A child that understands nothing but commands: whatever it is handed IS a command (the shell)."""
    accepts = descriptor.get("accepts")
    return isinstance(accepts, list) and accepts == [KIND_COMMAND]


# ── the whole file: one canonical shape for every agent ────────────────────
#
# `.las-agent.json` is everything LAS knows about one agent instance: who it
# is (name, locale, tts_voice, pronunciation), how it speaks (response_length_hint),
# what it is for — the scope ladder (docs/adr/0001) as direct strings
# (short_description, long_description) plus `scope_docs`, the documents that
# carry the longer rungs — and how its sessions are routed (`sessions`).
#
# `scope_docs` lists paths relative to the agent's folder, most specific
# first. Each implementation picks what identifies it: a README, a
# `.vxia-scope.<N>.md` (vortexia's file convention), any other doc. When the
# file does not say, it is discovered: `.vxia-scope.<N>.md` ascending, then
# README.md — the scan order vortexia's ladder uses.

DEFAULT_RESPONSE_LENGTH_HINT = 40
# `tts_voice` is the Kokoro id the agent speaks with (cli/voice_catalog.py) —
# written into every file so the voice has a name you can see, compare and
# hand to a friend. The old `voice` key (a macOS `say` name) is migrated to
# `locale` and dropped: it only ever decided the language.
LEGACY_KEYS = ("voice",)
CANONICAL_KEYS = ("name", "locale", "tts_voice", "pronunciation", "created", "response_length_hint",
                  "short_description", "long_description", "scope_docs")


def discover_scope_docs(agent_dir: str | Path) -> list:
    """The identity documents present in `agent_dir`, in scope-ladder order (relative paths)."""
    agent_dir = Path(agent_dir)
    rungs = []
    for f in agent_dir.glob(".vxia-scope.*.md"):
        middle = f.name[len(".vxia-scope."):-len(".md")]
        if middle.isdigit():
            rungs.append((int(middle), f.name))
    docs = [name for _, name in sorted(rungs)]
    if (agent_dir / "README.md").is_file():
        docs.append("README.md")
    return docs


def normalized_agent_config(config: dict, agent_dir: str | Path) -> dict:
    """`config` completed to the canonical shape — never overwriting a value the file already states.

    Canonical keys come first in a fixed order, anything else the agent keeps
    (e.g. `ports`) after them, `sessions` last. Missing values get their
    defaults: locale from the legacy `voice` name (then dropped), tts_voice
    the Kokoro voice the agent already speaks with (its name hash — pinning it
    changes nothing audible), pronunciation from the name, empty descriptions,
    discovered `scope_docs`, the default `sessions` section (a present one
    keeps its choices and gains any runtime it lacks).
    """
    from cli import voice_catalog
    name = config.get("name", "")
    locale = voice_catalog.locale_of(config)
    defaults = {
        "name": name,
        "locale": locale,
        "tts_voice": None,
        "pronunciation": name,
        "created": "",
        "response_length_hint": DEFAULT_RESPONSE_LENGTH_HINT,
        "short_description": "",
        "long_description": "",
        "scope_docs": None,
    }
    out = {}
    for key in CANONICAL_KEYS:
        if key in config:
            out[key] = config[key]
        elif key == "tts_voice":
            out[key] = voice_catalog.hashed_voice(name, locale)
        elif key == "scope_docs":
            out[key] = discover_scope_docs(agent_dir)
        else:
            out[key] = defaults[key]
    for key, value in config.items():
        if key not in out and key != "sessions" and key not in LEGACY_KEYS:
            out[key] = value
    base = default_sessions_config()
    current = _dict(config.get("sessions"))
    out["sessions"] = {**base, **current, "runtimes": {**base["runtimes"], **_dict(current.get("runtimes"))}}
    return out


def merge_config_patch(config: dict, patch: dict) -> dict:
    """`config` with `patch` applied: top-level keys replaced, `sessions` merged one level deep (its `runtimes` per key)."""
    result = copy.deepcopy(config)
    for key, value in patch.items():
        if key == "sessions" and isinstance(value, dict):
            # A file that never had the section gets the whole of it — the
            # descriptors included — so the agent's file shows, in one
            # place, what a router can know about its children.
            current = dict(result["sessions"]) if isinstance(result.get("sessions"), dict) else default_sessions_config()
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


class BrokenAgentConfig(ValueError):
    """The file exists but is not a JSON object — nothing may overwrite it."""


def read_agent_config(path: Path, *, strict: bool = False) -> dict:
    """The file as a dict. A missing file is {}. A broken one is {} too — unless
    `strict`, which raises BrokenAgentConfig so a writer never replaces a
    hand-edited file that merely has a trailing comma with the patch alone."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        if strict:
            raise BrokenAgentConfig(f"{path} is not valid JSON: {exc}") from exc
        return {}
    if not isinstance(data, dict):
        if strict:
            raise BrokenAgentConfig(f"{path} is not a JSON object")
        return {}
    return data


def write_agent_config(path: Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ── las-friends: the agents this one is linked to ──────────────────────────
#
#     "friends": ["Vortexia", "Teli"]
#
# A plain list of agent names, in the order they were added. Directed, like a
# follow: A listing B says nothing about B listing A — when both do, the link
# is mutual. The widget's children drawer shows them next to the sessions
# (list tab and 2D panel tab) and an agent like a coach can message them all.

FRIENDS_KEY = "friends"


def friends_of(config: dict | None) -> list:
    """The declared friends of `config`: unique non-empty names, in file order, never the agent itself.

    Tolerant of a hand-edited file — anything that is not a string is ignored."""
    config = _dict(config)
    declared = config.get(FRIENDS_KEY)
    if not isinstance(declared, list):
        return []
    own = config.get("name")
    out = []
    for item in declared:
        if isinstance(item, str) and item.strip() and item.strip() != own and item.strip() not in out:
            out.append(item.strip())
    return out


def with_friend(config: dict | None, friend: str, *, linked: bool = True) -> list:
    """The friends list of `config` after adding (`linked`) or removing `friend` — order kept, new ones appended."""
    current = friends_of(config)
    if linked:
        return current if friend in current else current + [friend]
    return [f for f in current if f != friend]


# ── map elements: what an agent added to its map by hand ───────────────────
#
#     "map": [
#       {"type": "repo", "path": "relay-ros"},
#       {"type": "url", "url": "https://github.com/x/y", "label": "Board"}
#     ]
#
# The map (docs/adr/0007) shows an agent's sessions and friends, which are
# derived, plus these: elements added with `las map add`. A list, in the
# order added; each element is identified by its type and its target
# (`repo:<path>`, `url:<url>`). A repo path inside the agent's folder is kept
# relative to it, so moving the folder keeps the map.

MAP_KEY = "map"
MAP_TYPES = ("repo", "url")
_MAP_TARGET = {"repo": "path", "url": "url"}


def map_element_id(element: dict) -> str:
    """`<type>:<target>` — the stable id `las map remove` takes."""
    kind = element.get("type")
    return f"{kind}:{element.get(_MAP_TARGET.get(kind, ''), '')}"


def map_elements_of(config: dict | None) -> list:
    """The declared map elements of `config`: known types with a non-empty target, unique by id, in file order.

    Tolerant of a hand-edited file — anything malformed is ignored, never a crash."""
    declared = _dict(config).get(MAP_KEY)
    if not isinstance(declared, list):
        return []
    out, seen = [], set()
    for item in declared:
        if not isinstance(item, dict) or item.get("type") not in MAP_TYPES:
            continue
        target = item.get(_MAP_TARGET[item["type"]])
        if not isinstance(target, str) or not target.strip():
            continue
        element = {"type": item["type"], _MAP_TARGET[item["type"]]: target.strip()}
        if isinstance(item.get("label"), str) and item["label"].strip():
            element["label"] = item["label"].strip()
        eid = map_element_id(element)
        if eid not in seen:
            seen.add(eid)
            out.append(element)
    return out


def with_map_element(config: dict | None, element: dict, *, added: bool = True) -> list:
    """The map list after adding `element` (replacing one with the same id, in place) or removing it (by id)."""
    current = map_elements_of(config)
    eid = map_element_id(element)
    if not added:
        return [e for e in current if map_element_id(e) != eid]
    if any(map_element_id(e) == eid for e in current):
        return [element if map_element_id(e) == eid else e for e in current]
    return current + [element]
