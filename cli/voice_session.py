"""Voice sessions — Claude or Codex with no terminal, one conversation (docs/adr/0008).

`las claude --headless` / `las claudeRelay --headless` / `las codex --headless`
connect a detached session (docs/adr/0006) whose command is `las voice-turn
RUNTIME CONV`: every message runs ONE non-interactive turn of the same
conversation — `claude -p --resume CONV`, `codex exec resume THREAD` — and the
final message is the answer, spoken in the agent's voice when the mic asked.
Nobody ever sees a terminal: the human dictates, hears, dictates the reply.

Continuity: CONV is the voice session's own key; the runtime's conversation id
lives in VOICE_DIR/CONV.thread, the same way for both runtimes:
  - no file → a new conversation: Claude gets a fresh `--session-id`, Codex
    names its thread in the first `thread.started` event; either is written;
  - a file → `claude -p --resume ID` / `codex exec resume ID`;
  - `--last` in the file (`--resume` with no id) → this folder's most recent
    conversation (Claude: newest transcript of the folder, resolved at start;
    Codex: `codex exec resume --last`, which filters by folder itself).
Resume = the file pre-written at start. Clear = a dictated "/clear" (or "nueva
conversación") deletes it: the next turn starts a new conversation.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import uuid
from pathlib import Path

# Set in every turn's environment: the end-of-turn hooks (cli/turn_hook.py)
# stay out — the answer IS the closing report, a `las speak` would say it twice.
VOICE_ENV = "LAS_VOICE_SESSION"
VOICE_DIR = Path(os.getenv("LAS_VOICE_DIR", str(Path.home() / ".las" / "voice")))
TURN_TIMEOUT_S = int(os.getenv("LAS_VOICE_TURN_TIMEOUT", "1800"))
RUNTIMES = ("claude", "codex")
LAST = "--last"
# A dictation that only asks for a fresh start (transcribed with or without the
# slash, a final period, any case) — the voice equivalent of typing /clear.
CLEAR_RE = re.compile(r"^\s*(?:/|barra\s+)?(?:clear|reset|new conversation|nueva conversaci[oó]n|"
                      r"(?:borrar|borra|limpiar|limpia) (?:la )?conversaci[oó]n)\s*[.!]?\s*$", re.I)


def voice_instructions(name: str, locale: str) -> str:
    spanish = str(locale or "").lower().startswith("es")
    lang = "Spanish" if spanish else "English"
    return (
        f"You are the voice-only session of the LAS agent {name!r}. There is NO terminal: the human dictates "
        f"through a microphone and HEARS your final message through text-to-speech, nobody reads it. "
        f"Do the work they ask for with your tools as usual. Then end with a short spoken answer in {lang}: "
        f"plain sentences, no markdown, no lists, no code, no tables, no URLs or file paths unless asked — "
        f"two or three sentences unless they ask for more. If you need a decision, ask ONE short question and "
        f"stop: their next dictation is the answer. This session is ALREADY connected to LAS ({VOICE_ENV}=1): skip "
        f"every /las-agent session-start step — no `las bridge status`, `las agent register`, `las agent poll`, "
        f"no probe ack, no session title, no `las speak`, no closing report — and never mention live delivery or "
        f"`las claude --resume`. LAS speaks your final message for you."
    )


def new_conversation() -> str:
    return str(uuid.uuid4())


# ── Claude ──────────────────────────────────────────────────────────────────
def claude_config_dir(account: str | None = None) -> Path:
    if account:
        return Path.home() / f".claude-{account}"
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def claude_project_dir(cwd: str, config_dir: Path) -> Path:
    """Where Claude keeps a folder's transcripts: every non-alphanumeric char of the path → '-'."""
    return config_dir / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def latest_claude_conversation(cwd: str, config_dir: Path) -> str | None:
    found = sorted(claude_project_dir(cwd, config_dir).glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
    return found[-1].stem if found else None


def claude_argv(claude: str, conv_id: str, text: str, instructions: str, resume: bool) -> list:
    return [claude, "-p", "--resume" if resume else "--session-id", conv_id, "--output-format", "text",
            "--permission-mode", "bypassPermissions", "--append-system-prompt", instructions, text]


# ── Codex ───────────────────────────────────────────────────────────────────
def thread_file(conv: str) -> Path:
    return VOICE_DIR / f"{conv}.thread"


def current_id(conv: str) -> str:
    f = thread_file(conv)
    return f.read_text().strip() if f.exists() else ""


def set_id(conv: str, conv_id: str) -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    thread_file(conv).write_text(conv_id)


def clear(conv: str) -> None:
    thread_file(conv).unlink(missing_ok=True)


def prepare_resume(runtime: str, conv: str, resume: str, cwd: str, account: str | None = None) -> str:
    """Point the new voice session `conv` at an existing conversation: an id, or
    LAST = this folder's most recent. Returns the id (LAST for Codex, resolved by Codex)."""
    if resume == LAST and runtime == "claude":
        found = latest_claude_conversation(cwd, claude_config_dir(account))
        if not found:
            raise ValueError(f"no Claude conversation recorded for {cwd}")
        resume = found
    set_id(conv, resume)
    return resume


def codex_argv(conv: str, text: str, instructions: str, cwd: str) -> list:
    current = current_id(conv)
    common = ["--json", "--yolo", "--skip-git-repo-check", "-c", f"developer_instructions={json.dumps(instructions)}"]
    if current == LAST:
        return ["codex", "exec", "resume", LAST, *common, text]
    if current:
        return ["codex", "exec", "resume", current, *common, text]
    return ["codex", "exec", "-C", cwd, *common, text]


def parse_codex_events(lines) -> tuple[str | None, str]:
    """(thread id, last agent message) from `codex exec --json` output."""
    thread, answer = None, ""
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "thread.started":
            thread = e.get("thread_id") or thread
        item = e.get("item") or {}
        if e.get("type") == "item.completed" and item.get("type") == "agent_message" and item.get("text"):
            answer = item["text"]
    return thread, answer


# ── one turn ────────────────────────────────────────────────────────────────
def cleared_text(locale: str) -> str:
    return "Listo, conversación nueva." if str(locale or "").lower().startswith("es") else "Done, new conversation."


def failure_text(locale: str, detail: str) -> str:
    spanish = str(locale or "").lower().startswith("es")
    return (f"No pude completar ese turno: {detail}" if spanish else f"I couldn't finish that turn: {detail}")


def run_turn(runtime: str, conv: str, text: str, *, name: str, locale: str, cwd: str,
             account: str | None = None, run=subprocess.run, claude: str = "claude") -> str:
    """One turn of the conversation `conv`; returns what to say (never raises for a failed run)."""
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown voice runtime {runtime!r} (one of {', '.join(RUNTIMES)})")
    if CLEAR_RE.match(text or ""):
        clear(conv)
        return cleared_text(locale)
    env = {**os.environ, VOICE_ENV: "1"}
    instructions = voice_instructions(name, locale)
    started = None
    if runtime == "claude":
        if account:
            env["CLAUDE_CONFIG_DIR"] = str(claude_config_dir(account))
        conv_id = current_id(conv)
        if not conv_id:
            conv_id = started = str(uuid.uuid4())
            set_id(conv, conv_id)
        argv = claude_argv(claude, conv_id, text, instructions, resume=started is None)
    else:
        argv = codex_argv(conv, text, instructions, cwd)
    try:
        proc = run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TURN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return failure_text(locale, f"no answer after {TURN_TIMEOUT_S // 60} min")
    except OSError as err:
        if started:
            clear(conv)
        return failure_text(locale, str(err))
    if runtime == "codex":
        thread, answer = parse_codex_events(proc.stdout.splitlines())
        if thread:
            set_id(conv, thread)
    else:
        answer = proc.stdout.strip()
        if started and proc.returncode != 0 and not answer:
            clear(conv)  # nothing was recorded under that id: the next turn starts afresh
    if proc.returncode != 0 and not answer:
        last = (proc.stderr or "").strip().splitlines()[-1:] or [f"exit {proc.returncode}"]
        return failure_text(locale, last[0][:200])
    return answer.strip()


def resume_from_args(args, runtime: str = "claude") -> str | None:
    """Claude's spelling (`--resume [ID]`, `-r`, `--continue`/`-c`) or Codex's
    (`resume [ID|--last]`, `--resume`) → the id, LAST with no id, None when absent.
    (`-c` is Codex's config flag, so it means "continue" only for Claude.)"""
    args = list(args)
    flags = ("--resume", "-r", "--continue", "-c") if runtime == "claude" else ("resume", "--resume")
    for i, a in enumerate(args):
        if a.startswith("--resume="):
            return a.split("=", 1)[1] or LAST
        if a in flags:
            nxt = args[i + 1] if i + 1 < len(args) else ""
            return LAST if a in ("--continue", "-c") or not nxt or nxt.startswith("-") else nxt
    return None


def turn_command(las: str, runtime: str, conv: str, account: str | None = None) -> str:
    """The command line the detached session runs per message (the text is appended)."""
    argv = [las, "voice-turn", runtime, conv] + (["--account", account] if account else [])
    return shlex.join(argv)
