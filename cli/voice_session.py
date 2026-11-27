"""Voice sessions — Claude or Codex with no terminal, one conversation (docs/adr/0008).

`las claude --headless` / `las claudeRelay --headless` / `las codex --headless`
connect a detached session (docs/adr/0006) whose command is `las voice-turn
RUNTIME CONV`: every message runs ONE non-interactive turn of the same
conversation — `claude -p --resume CONV`, `codex exec resume THREAD` — and the
final message is the answer, spoken in the agent's voice when the mic asked.
Nobody ever sees a terminal: the human dictates, hears, dictates the reply.

Continuity, per runtime:
  - Claude takes a session id we choose: the first turn creates it
    (`--session-id CONV`), every later one resumes it (`--resume CONV`).
  - Codex picks its own thread id: the first turn's `thread.started` event
    names it and it is kept in VOICE_DIR/CONV.thread for the next turns.
"""
from __future__ import annotations

import json
import os
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


def claude_conversation_exists(conv: str, config_dir: Path) -> bool:
    return any((config_dir / "projects").glob(f"*/{conv}.jsonl"))


def claude_argv(claude: str, conv: str, text: str, instructions: str, resume: bool) -> list:
    return [claude, "-p", "--resume" if resume else "--session-id", conv, "--output-format", "text",
            "--permission-mode", "bypassPermissions", "--append-system-prompt", instructions, text]


# ── Codex ───────────────────────────────────────────────────────────────────
def codex_thread_file(conv: str) -> Path:
    return VOICE_DIR / f"{conv}.thread"


def codex_argv(conv: str, text: str, instructions: str, cwd: str) -> list:
    thread = codex_thread_file(conv)
    common = ["--json", "--yolo", "--skip-git-repo-check", "-c", f"developer_instructions={json.dumps(instructions)}"]
    if thread.exists() and thread.read_text().strip():
        return ["codex", "exec", "resume", thread.read_text().strip(), *common, text]
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
def failure_text(locale: str, detail: str) -> str:
    spanish = str(locale or "").lower().startswith("es")
    return (f"No pude completar ese turno: {detail}" if spanish else f"I couldn't finish that turn: {detail}")


def run_turn(runtime: str, conv: str, text: str, *, name: str, locale: str, cwd: str,
             account: str | None = None, run=subprocess.run, claude: str = "claude") -> str:
    """One turn of the conversation `conv`; returns what to say (never raises for a failed run)."""
    env = {**os.environ, VOICE_ENV: "1"}
    instructions = voice_instructions(name, locale)
    if runtime == "claude":
        config_dir = claude_config_dir(account)
        if account:
            env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        argv = claude_argv(claude, conv, text, instructions, claude_conversation_exists(conv, config_dir))
    elif runtime == "codex":
        argv = codex_argv(conv, text, instructions, cwd)
    else:
        raise ValueError(f"unknown voice runtime {runtime!r} (one of {', '.join(RUNTIMES)})")
    try:
        proc = run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TURN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return failure_text(locale, f"no answer after {TURN_TIMEOUT_S // 60} min")
    except OSError as err:
        return failure_text(locale, str(err))
    if runtime == "codex":
        thread, answer = parse_codex_events(proc.stdout.splitlines())
        if thread:
            VOICE_DIR.mkdir(parents=True, exist_ok=True)
            codex_thread_file(conv).write_text(thread)
    else:
        answer = proc.stdout.strip()
    if proc.returncode != 0 and not answer:
        last = (proc.stderr or "").strip().splitlines()[-1:] or [f"exit {proc.returncode}"]
        return failure_text(locale, last[0][:200])
    return answer.strip()


def turn_command(las: str, runtime: str, conv: str, account: str | None = None) -> str:
    """The command line the detached session runs per message (the text is appended)."""
    argv = [las, "voice-turn", runtime, conv] + (["--account", account] if account else [])
    return shlex.join(argv)
