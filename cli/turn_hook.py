"""The end-of-turn hook: every LAS agent says what it just did.

The closing report (las-agent skill §2) is what feeds the widget's chat, the
phone's chat and its notifications: a `las speak` at the end of each turn.
When the human talks to the widget mic the agent remembers it; when the human
types — or dictates with Claude Code's own voice input — it often doesn't, and
the chat goes quiet. LAS has no AI to write that summary itself, so the hook
asks the agent that did the work:

* Claude Code — a `Stop` hook (`las hook claude-stop`). If the turn ends with
  no `las speak` from this agent since the turn's prompt, the hook speaks the
  report ITSELF from the agent's own final message (its first sentence,
  markdown stripped) — quietly, no blocked stop, no extra turn: a blocked stop
  showed up as a yellow "Stop hook reported a problem" plus a second turn,
  far too often (2026-11-27). Only a turn with no final text gets the old
  nudge (block once; `stop_hook_active` ends it, never a loop).
* Claude Code — a `UserPromptSubmit` hook (`las hook claude-prompt`): a prompt
  typed (or dictated with Claude's own voice input) into the terminal is a human
  input on the Mac, so auto voice routing sends the reply's voice to the Mac —
  vortexia never sees it, so without this it stayed on the phone that dictated last.
* Codex — its `notify` program (`las hook codex-notify`), run after each turn
  with the turn's JSON. Same rule: its `last-assistant-message` is spoken as
  the report; only without one, the nudge goes the way every
  other message reaches it: into this agent's codex session's mailbox, typed
  into the TUI that `las codex` runs. A turn whose prompt WAS that nudge is
  never nudged again.

Never on housekeeping turns (a channel probe, a title request, a cc copy, a
background-task notice): those get no report by the skill's own rule. Outside
an agent folder, or with the backend down, the hook does nothing — it must
never get in the way of a session.

`ensure_installed()` writes both entries, idempotently, keeping whatever else
is there: run by `las claude`/`las codex` and by `las update`.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from cli.agent_config import read_agent_config
from cli.path_utils import agent_config_path

BACKEND = os.environ.get("LAS_BACKEND_URL", "http://localhost:8700")
NUDGE_MARK = "[las-closing-report]"
HOUSEKEEPING = (
    'kind="probe"', 'kind="title-request"', 'kind="cc"', "[las-channel-probe]",
    "[las-session-title]", "<task-notification>", NUDGE_MARK,
)
STATE_FILE = Path.home() / ".las" / "codex-turns.json"


# ── shared ──────────────────────────────────────────────────────────────────
def agent_here(cwd: str) -> tuple[str, dict] | None:
    # Upward only: find_nearest_agent_dir also searches DOWN, and a session in
    # a plain folder must not report as whatever agent lives below it.
    start = Path(cwd)
    d = next((p for p in [start, *start.parents] if agent_config_path(p)), None)
    if not d:
        return None
    try:
        cfg = read_agent_config(agent_config_path(d) or Path(d) / ".las-agent.json") or {}
    except Exception:
        return None
    name = cfg.get("name")
    return (name, cfg) if name else None


def is_housekeeping(text: str) -> bool:
    return any(m in text for m in HOUSEKEEPING)


def spoke_since(name: str, since_ms: int, fetch=None) -> bool | None:
    """Did `name` speak (a `las speak`, recorded in its chat) after `since_ms`?
    None when the backend can't tell — then nobody gets nudged."""
    url = f"{BACKEND}/agents/{urllib.parse.quote(name)}/chat?after={int(since_ms)}&limit=200"
    try:
        body = fetch(url) if fetch else json.loads(urllib.request.urlopen(url, timeout=2).read())
    except Exception:
        return None
    return any(m.get("kind") == "speak" for m in body.get("messages", []))


def nudge_text(name: str, cfg: dict) -> str:
    spanish = str(cfg.get("locale", "")).lower().startswith("es")
    verb = "Reportando" if spanish else "Reporting"
    hint = cfg.get("response_length_hint") or cfg.get("report_max_chars") or 40
    return (f"{NUDGE_MARK} This turn ended without your LAS closing report. Speak it now, in "
            f"{'Spanish' if spanish else 'English'} (your locale), about {hint} characters, as a soft target: "
            f"las speak \"{verb}: <what you just did>\" --name {shlex.quote(name)} — then stop. "
            f"Nothing else: no new work, no other reply.")


# ── the report, from the agent's own words ──────────────────────────────────
def _plain(line: str) -> str:
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)          # [label](url) -> label
    line = re.sub(r"^\s*(?:[-•>]|\d+[.)])\s+", "", line)            # list / quote markers
    return re.sub(r"[`*#|]+", "", line).strip()


def first_sentence(text: str) -> str:
    """The first whole sentence of the agent's final message, as plain speech.
    Headings and code blocks are skipped; a heading is used only when nothing else is there."""
    heading = ""
    for raw in re.sub(r"```.*?```", "\n", text or "", flags=re.S).splitlines():
        line = _plain(raw)
        if not line:
            continue
        if raw.lstrip().startswith("#"):
            heading = heading or line
            continue
        m = re.match(r"(.+?[.!?…])(?:\s|$)", line)
        return (m.group(1) if m else line).rstrip(".!?…:; ").strip()
    return heading.rstrip(".!?…:; ")


def report_text(name: str, cfg: dict, final_message: str) -> str | None:
    summary = first_sentence(final_message)
    if not summary:
        return None
    verb = "Reportando" if str(cfg.get("locale", "")).lower().startswith("es") else "Reporting"
    return f"{verb}: {summary}. {name}."


def speak_report(name: str, text: str, post=None) -> bool:
    """Queue `text` in `name`'s voice (the same queue `las speak` uses)."""
    body = {"text": text, "name": name}
    try:
        if post:
            post(body)
        else:
            req = urllib.request.Request(f"{BACKEND}/queue/speak", data=json.dumps(body).encode(), headers={"content-type": "application/json"})
            urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        return False
    return True


def last_assistant_text(transcript: Path, since_ms: int) -> str:
    """The last assistant text written after `since_ms` (the turn's final message)."""
    last = ""
    try:
        lines = transcript.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "assistant":
            continue
        try:
            ts = int(datetime.fromisoformat(str(e.get("timestamp")).replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            continue
        content = (e.get("message") or {}).get("content")
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"] if isinstance(content, list) else []
        if ts >= since_ms and any(t.strip() for t in texts):
            last = "\n".join(texts)
    return last


# ── Claude Code: Stop hook ──────────────────────────────────────────────────
def _text_of(content) -> str | None:
    """A user entry's prompt text; None for a tool result (not a new prompt)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return None


def turn_prompt(transcript: Path) -> tuple[int, str] | None:
    """(timestamp ms, text) of the prompt that started the current turn."""
    last = None
    try:
        lines = transcript.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "user" or e.get("isMeta"):
            continue
        text = _text_of((e.get("message") or {}).get("content"))
        if text is None:
            continue
        try:
            ts = int(datetime.fromisoformat(str(e.get("timestamp")).replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            continue
        last = (ts, text)
    return last


def voice_turn() -> bool:
    """A turn of a voice session (cli/voice_session.py): its final message is
    spoken by LAS already — no nudge, and it is not the human typing here."""
    return bool(os.environ.get("LAS_VOICE_SESSION"))


def claude_stop(payload: dict, fetch=None, speak_post=None) -> dict | None:
    """The Stop hook's decision: None (let it stop — after speaking the report
    from the final message when the agent didn't), or a {"decision": "block"}
    nudge when there is no final message to speak."""
    if payload.get("stop_hook_active") or voice_turn():
        return None
    here = agent_here(payload.get("cwd") or os.getcwd())
    if not here:
        return None
    name, cfg = here
    prompt = turn_prompt(Path(payload.get("transcript_path") or ""))
    if not prompt:
        return None
    ts, text = prompt
    if is_housekeeping(text) or re.search(r"<command-name>|<local-command", text):
        return None
    if spoke_since(name, ts, fetch) is not False:
        return None
    final = payload.get("last_assistant_message") or last_assistant_text(Path(payload.get("transcript_path") or ""), ts)
    report = report_text(name, cfg, final)
    if report and speak_report(name, report, speak_post):
        return None
    return {"decision": "block", "reason": nudge_text(name, cfg)}


# ── Claude Code: UserPromptSubmit hook ──────────────────────────────────────
def note_terminal_input(name: str, post=None) -> bool:
    url = f"{BACKEND}/agents/{urllib.parse.quote(name)}/terminal-input"
    try:
        if post:
            post(url)
        else:
            req = urllib.request.Request(url, data=b"{}", headers={"content-type": "application/json"})
            urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        return False
    return True


def claude_prompt(payload: dict, post=None) -> bool:
    """A prompt the human typed here (not a channel event, not a slash command):
    the agent's voice should come out on this Mac, not on the phone that
    dictated last. True = noted."""
    text = str(payload.get("prompt") or "")
    if voice_turn() or not text.strip() or "<channel" in text or text.lstrip().startswith("/") or is_housekeeping(text):
        return False
    here = agent_here(payload.get("cwd") or os.getcwd())
    return bool(here) and note_terminal_input(here[0], post)


# ── Codex: notify ───────────────────────────────────────────────────────────
def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def codex_notify(payload: dict, fetch=None, send=None, now=time.time, post=None, speak_post=None) -> bool:
    """After a Codex turn that didn't speak: speak the report from its final
    message, or (no final message) nudge its session. True = nudged."""
    if payload.get("type") != "agent-turn-complete" or voice_turn():
        return False
    thread = str(payload.get("thread-id") or payload.get("turn-id") or "?")
    state = _load_state()
    t_now = int(now() * 1000)
    since = int(state.get(thread, t_now - 10 * 60 * 1000))
    state[thread] = t_now
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(dict(list(state.items())[-200:])))
    except OSError:
        pass
    here = agent_here(payload.get("cwd") or os.getcwd())
    if not here:
        return False
    name, cfg = here
    asked = "\n".join(str(m) for m in payload.get("input-messages") or [])
    if is_housekeeping(asked):
        return False
    if asked.strip() and "[LAS message from" not in asked:
        note_terminal_input(name, post)  # typed in the TUI: voice back on the Mac
    if spoke_since(name, since, fetch) is not False:
        return False
    report = report_text(name, cfg, str(payload.get("last-assistant-message") or ""))
    if report and speak_report(name, report, speak_post):
        return False
    body = {"message": nudge_text(name, cfg), "to": name, "session": "codex", "source": "system", "from_agent": "LAS"}
    try:
        if send:
            send(body)
        else:
            req = urllib.request.Request(f"{BACKEND}/agents/send", data=json.dumps(body).encode(), headers={"content-type": "application/json"})
            urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        return False
    return True


# ── installing both ─────────────────────────────────────────────────────────
def _las_bin() -> str:
    """This very `las` (the one running), else the one on PATH — always a file named `las`."""
    me = Path(sys.argv[0])
    if me.name == "las" and os.access(me, os.X_OK):
        return str(me.absolute())
    found = shutil.which("las")
    return found if found and Path(found).name == "las" else "las"


def claude_settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "settings.json"


def ensure_claude_hook(path: Path | None = None, las: str | None = None) -> bool:
    """Add the Stop hook to Claude Code's settings.json (once; keeps everything else)."""
    path = path or claude_settings_path()
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        return False  # a file we can't parse is not ours to rewrite
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    stop = hooks.get("Stop") if isinstance(hooks.get("Stop"), list) else []
    prompt = hooks.get("UserPromptSubmit") if isinstance(hooks.get("UserPromptSubmit"), list) else []
    has_stop = any("hook claude-stop" in json.dumps(g) for g in stop)
    has_prompt = any("hook claude-prompt" in json.dumps(g) for g in prompt)
    if has_stop and has_prompt:
        return True
    las_q = shlex.quote(las or _las_bin())
    if not has_stop:
        stop.append({"hooks": [{"type": "command", "command": f"{las_q} hook claude-stop", "timeout": 10}]})
    if not has_prompt:
        prompt.append({"hooks": [{"type": "command", "command": f"{las_q} hook claude-prompt", "timeout": 5}]})
    hooks["Stop"] = stop
    hooks["UserPromptSubmit"] = prompt
    settings["hooks"] = hooks
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return True


def ensure_codex_notify(path: Path | None = None, las: str | None = None) -> bool:
    """Set Codex's `notify` to our hook — only when nothing else holds it."""
    path = path or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    if not path.parent.exists():
        return False  # no Codex on this machine
    text = path.read_text() if path.exists() else ""
    if re.search(r"^\s*notify\s*=", text, re.M):
        return "codex-notify" in text
    line = f"notify = {json.dumps([las or _las_bin(), 'hook', 'codex-notify'])}\n"
    # top-level keys must come before the first [table]
    m = re.search(r"^\[", text, re.M)
    text = text[: m.start()] + line + "\n" + text[m.start():] if m else (text + ("\n" if text and not text.endswith("\n") else "") + line)
    path.write_text(text)
    return True


def ensure_installed() -> None:
    try:
        ensure_claude_hook()
    except Exception:
        pass
    try:
        ensure_codex_notify()
    except Exception:
        pass
