"""`las local` — this agent as a conversational session on a local model.

A session runtime like `claude`, `codex` and `shell`. The brain is Pulpo's
"las-local" flow (Pulpo owns the model, the prompt and which tool or skill a
turn needs — contract: pulpo/_/docs/las-local-contract.md). This module is
the thin client around it, and owns only what touches this machine:

  - the inputs, handled one at a time in arrival order: the human at this
    terminal (stdin) and the agent's vortexia mailbox, through a
    `las-bridge stdout` child that registers this terminal as session
    runtime "local" (the widget's 👥 list)
  - the tools that act here (read a file, run a command, …), executed and
    confirmed here — Pulpo returns the call, never runs it
  - the answer, sent back where the input came from: printed here, sent to
    the sending agent (`las agent send`), and spoken when the human dictated

One turn: the conversation goes to the flow, one step at a time; a step
answers or asks for tool calls, whose results go back on the next step, up
to MAX_TOOL_ROUNDS. Pulpo keeps no state: the conversation lives here.

Skills are markdown files with a `name:`/`description:` front matter, found
in <agent>/.las-local/skills/ and ~/.las/local-skills/; they're sent with
every step and the flow loads a body only when it needs it.
"""
from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


FLOW_URL = os.getenv("LAS_LOCAL_FLOW_URL", "http://localhost:9010/api/flows/las-local/trigger/entrada")
STEP_TIMEOUT_MS = int(os.getenv("LAS_LOCAL_STEP_TIMEOUT_MS", "120000"))   # a cold model load is ~10 s; the flow caps at 180 s
MAX_TOOL_ROUNDS = 4
HISTORY_TURNS = 12          # user+assistant messages kept (tool chatter is dropped between turns)
TOOL_OUTPUT_MAX = 4000      # chars of a tool result handed back to the model

# Marks every answer this runtime sends to an agent; an incoming message that
# carries it is someone's automatic answer and is shown, never answered —
# two `las local` (or one and a Claude that acknowledges) can't ping-pong.
# `las agent send` has no kind for this, so the marker lives in the text.
AUTO_REPLY_MARK = "↩ "
# Belt and braces for senders that don't mark their answers: at most this many
# automatic replies to one agent per minute; past it, the message is only shown.
REPLIES_PER_MINUTE = 3

MIC_SELFTEST_PING ='[las-mic-selftest] reply with just "OK" to confirm this session is listening.'


# ── tools ───────────────────────────────────────────────────────────────────

@dataclass
class Tool:
    name: str
    description: str                       # what the model reads to pick it
    parameters: dict                       # JSON schema of the arguments
    run: Callable[..., str]
    confirm: bool = False                  # ask y/N on the TTY before running

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


def _sh(argv: list, cwd: str | None = None, timeout: float = 60) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"error: {exc}"
    out = (p.stdout + (("\n" + p.stderr) if p.stderr.strip() else "")).strip()
    return out if p.returncode == 0 else f"exit {p.returncode}: {out}"


_SESSION_ROW = re.compile(r'^\s+(\S+)\s+(\S+)\s*(?:"(.*?)")?')


def flatten_sessions(text: str) -> str:
    """`las agent sessions --all` nests sessions under agent headers; a 4B model
    read the session ids as agent names. One self-contained line per session."""
    out, agent = [], None
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            agent = line.strip()
            continue
        m = _SESSION_ROW.match(line)
        if agent and m:
            title = f' — working on "{m.group(3)}"' if m.group(3) else ""
            out.append(f"agent {agent}: one {m.group(2)} terminal open{title}")
    return "\n".join(out) or text


def _inside(base: Path, path: str) -> Path:
    """`path` resolved under `base`; refuses to leave it."""
    target = (base / path).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"{path} is outside the agent folder")
    return target


def default_tools(agent: str, agent_dir: str, las: str = "las") -> list[Tool]:
    base = Path(agent_dir).resolve()

    def read_file(path: str) -> str:
        try:
            p = _inside(base, path)
            return p.read_text(errors="replace")[:TOOL_OUTPUT_MAX]
        except (OSError, ValueError) as exc:
            return f"error: {exc}"

    def list_dir(path: str = ".") -> str:
        try:
            p = _inside(base, path or ".")
            return "\n".join(sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())[:200])
        except (OSError, ValueError) as exc:
            return f"error: {exc}"

    obj = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}  # noqa: E731
    s = {"type": "string"}
    return [
        Tool("list_agents", "See which agents of the society exist, which terminals (sessions) each has open and what they work on.",
             obj({}), lambda: flatten_sessions(_sh([las, "agent", "sessions", "--all"]))),
        Tool("send_to_agent", "Send a message to another agent of the society (by its name) — ask it something or hand it a task.",
             obj({"to": s, "text": s}, ("to", "text")),
             lambda to, text: _sh([las, "agent", "send", "--to", to, "--from", agent, text])),
        Tool("speak", "Say something out loud with this agent's voice.",
             obj({"text": s}, ("text",)), lambda text: _sh([las, "speak", text, "--name", agent])),
        Tool("ports", "Audit the society's port registry: which ports are claimed and listening right now, by which agent (not a file).",
             obj({}), lambda: _sh([las, "ports", "audit"])),
        Tool("read_file", "Read a text file inside this agent's folder.",
             obj({"path": s}, ("path",)), read_file),
        Tool("list_dir", "List the files of a folder inside this agent's folder.",
             obj({"path": s}), list_dir),
        Tool("run_shell", "Run a shell command in this agent's folder (asks the human first).",
             obj({"command": s}, ("command",)),
             lambda command: _sh(["/bin/zsh", "-lc", command], cwd=str(base), timeout=120), confirm=True),
    ]


# ── skills ──────────────────────────────────────────────────────────────────

@dataclass
class Skill:
    name: str
    description: str
    body: str


_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def parse_skill(text: str, fallback_name: str) -> Skill | None:
    m = _FRONT.match(text)
    meta, body = ({}, text) if not m else ({}, m.group(2))
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if v:
                meta[k.strip()] = v.strip().strip("\"'")
    desc = meta.get("description", "").strip()
    if not desc:
        return None   # the model can't pick what it can't read
    return Skill(meta.get("name", fallback_name).strip() or fallback_name, desc, body.strip())


def skill_dirs(agent_dir: str) -> list[Path]:
    extra = [Path(p) for p in os.getenv("LAS_LOCAL_SKILLS", "").split(os.pathsep) if p]
    return [Path(agent_dir) / ".las-local" / "skills", Path.home() / ".las" / "local-skills", *extra]


def load_skills(dirs: list[Path]) -> list[Skill]:
    seen, out = set(), []
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                sk = parse_skill(f.read_text(errors="replace"), f.stem)
            except OSError:
                continue
            if sk and sk.name not in seen:        # nearest folder wins
                seen.add(sk.name)
                out.append(sk)
    return out


# ── the brain: one step of Pulpo's "las-local" flow ─────────────────────────

class StepError(Exception):
    pass


def pulpo_step(data: dict, *, url: str = FLOW_URL, timeout_ms: int = STEP_TIMEOUT_MS) -> dict:
    """POST one step; returns the flow's `response` ({type, messages, message, …})."""
    body = json.dumps({"wait": True, "timeout_ms": timeout_ms, "data": data}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_ms / 1000 + 5) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise StepError(f"Pulpo HTTP {exc.code}" + (" (step timed out)" if exc.code == 504 else "")) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise StepError(f"Pulpo unreachable at {url}: {exc}") from exc
    res = (out or {}).get("response")
    if not isinstance(res, dict) or res.get("type") not in ("answer", "tool_calls", "error"):
        raise StepError(f"unexpected answer from Pulpo: {str(out)[:200]}")
    return res


# ── the agent ───────────────────────────────────────────────────────────────

@dataclass
class Turn:
    text: str
    origin: str = "terminal"      # terminal | human (widget mic) | agent | system
    sender: str | None = None     # who to answer, for origin=agent


@dataclass
class LocalAgent:
    name: str
    agent_dir: str
    locale: str = "es"
    scope: str = ""
    tools: list[Tool] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    step: Callable[[dict], dict] = pulpo_step
    # (prompt, origin) → run it? `origin` is the turn's: an agent's message is
    # data, so the caller must never auto-approve it (see cli/commands/local.py).
    confirm: Callable[[str, str], bool] = lambda prompt, origin: False
    log: Callable[[str], None] = lambda line: None
    history: list = field(default_factory=list)

    def request(self, messages: list, tools: bool = True) -> dict:
        data = {"agent_name": self.name, "agent_dir": self.agent_dir, "agent_scope": self.scope,
                "locale": self.locale, "messages": messages}
        if tools:
            data["tools"] = [t.schema() for t in self.tools]
            if self.skills:
                data["skills"] = [{"name": s.name, "description": s.description, "body": s.body} for s in self.skills]
        return data

    def handle(self, turn: Turn) -> str:
        self._origin = turn.origin
        prefix = {"agent": f"[message from agent {turn.sender}] ", "human": "[dictated by the human] "}.get(turn.origin, "")
        self.history.append({"role": "user", "content": prefix + turn.text})
        messages = list(self.history)
        by_name = {t.name: t for t in self.tools}
        answer = ""
        for _ in range(MAX_TOOL_ROUNDS + 1):
            t0 = time.monotonic()
            try:
                res = self.step(self.request(messages))
            except StepError as exc:
                answer = f"(no answer: {exc})"
                break
            self.log(f"step {res.get('type')} {res.get('model') or ''} {time.monotonic() - t0:.1f}s")
            messages += res.get("messages") or []
            if res["type"] == "answer":
                answer = _strip_think((res.get("message") or {}).get("content") or "")
                break
            if res["type"] == "error":
                answer = f"(no answer: {res.get('error') or 'model error'})"
                break
            for call in (res.get("message") or {}).get("tool_calls") or []:
                fn = call.get("function") or {}
                result = self._run_tool(by_name.get(fn.get("name")), fn.get("name"), fn.get("arguments") or {})
                messages.append({"role": "tool", "tool_name": fn.get("name"), "content": result[:TOOL_OUTPUT_MAX]})
        else:
            answer = answer or "(stopped after too many tool calls)"
        self.history.append({"role": "assistant", "content": answer})
        self.history[:] = self.history[-HISTORY_TURNS:]
        return answer

    def _run_tool(self, tool: Tool | None, name, args) -> str:
        if tool is None:
            return f"error: no tool named {name}"
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        self.log(f"tool {name} {json.dumps(args, ensure_ascii=False)[:200]}")
        if tool.confirm and not self.confirm(f"{name} {json.dumps(args, ensure_ascii=False)}", getattr(self, "_origin", "agent")):
            return "the human declined to run this"
        try:
            return tool.run(**args) or "(no output)"
        except TypeError as exc:
            return f"error: bad arguments: {exc}"


_THINK = re.compile(r"<think>.*?</think>", re.S)


def _strip_think(text: str) -> str:
    return _THINK.sub("", text).strip()


# ── mailbox envelopes → turns ───────────────────────────────────────────────

def envelope_to_turn(env: dict, agent: str) -> Turn | None | str:
    """A turn to handle, None to ignore, or "selftest" for the mic self-test ping."""
    kind = env.get("kind") or "message"
    text = (env.get("text") or "").strip()
    if kind in ("cc", "probe", "speak", "mic-selftest-pong") or not text:
        return None
    if kind == "mic-selftest" or text == MIC_SELFTEST_PING:
        return "selftest"
    if kind == "title-request":
        return None   # answered by the runtime itself, not the model (see LocalRuntime)
    sender = env.get("from") or "?"
    if env.get("source") == "human" or sender == agent:
        return Turn(text, "human")
    if text.startswith(AUTO_REPLY_MARK):
        return None   # another runtime's automatic answer: never answered back (no ping-pong)
    return Turn(text, "agent" if env.get("source") != "system" else "system", sender)


class LocalRuntime:
    """Wires a LocalAgent to the terminal and the mailbox; one turn at a time."""

    def __init__(self, agent: LocalAgent, *, bridge_argv: list | None, las: str = "las",
                 stdin=sys.stdin, out=sys.stdout):
        self.agent, self.bridge_argv, self.las = agent, bridge_argv, las
        self.stdin, self.out = stdin, out
        self.inbox: queue.Queue = queue.Queue()
        self.bridge: subprocess.Popen | None = None
        self.last_topic = ""
        self.replied: dict[str, list] = {}

    def say(self, line: str = "") -> None:
        self.out.write(line + "\n")
        self.out.flush()

    def _read_stdin(self) -> None:
        for line in self.stdin:
            if line.strip():
                self.inbox.put(("terminal", line.strip()))
        self.inbox.put(("eof", None))

    def _read_bridge(self) -> None:
        for raw in self.bridge.stdout:
            try:
                self.inbox.put(("mailbox", json.loads(raw)))
            except ValueError:
                continue

    def make_title(self) -> str:
        """~34 chars (soft, never cut) written by the model; the topic itself if it can't."""
        topic = (self.last_topic or "").strip()
        if not topic:
            return "Agente local" if self.agent.locale.startswith("es") else "Local agent"
        lang = "Spanish" if self.agent.locale.startswith("es") else "English"
        ask = (f"Write a title of about 34 characters, in {lang}, for what this terminal is working on: "
               f"{topic}. Reply with the title only, no quotes.")
        try:
            res = self.agent.step(self.agent.request([{"role": "user", "content": ask}], tools=False))
            title = _strip_think((res.get("message") or {}).get("content") or "").strip().strip("\"'") if res.get("type") == "answer" else ""
        except StepError:
            title = ""
        return title.splitlines()[0] if title else topic

    def answer_title_request(self, env: dict) -> None:
        m = re.search(r"--session\s+(\S+)", env.get("text") or "")
        argv = [self.las, "agent", "title", self.make_title(), "--name", self.agent.name] + (["--session", m.group(1)] if m else [])
        _sh(argv)

    def may_reply(self, sender: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        recent = [t for t in self.replied.get(sender, []) if now - t < 60]
        if len(recent) >= REPLIES_PER_MINUTE:
            self.replied[sender] = recent
            return False
        self.replied[sender] = recent + [now]
        return True

    def deliver(self, turn: Turn, answer: str) -> None:
        self.say(f"{self.agent.name} › {answer}\n")
        if turn.origin == "agent" and turn.sender:
            if self.may_reply(turn.sender):
                _sh([self.las, "agent", "send", "--to", turn.sender, "--from", self.agent.name, AUTO_REPLY_MARK + answer])
            else:
                self.say(f"[no le respondo a {turn.sender}: más de {REPLIES_PER_MINUTE} respuestas automáticas en un minuto]")
        elif turn.origin == "human":
            _sh([self.las, "speak", answer, "--name", self.agent.name])

    @staticmethod
    def _exit_on_signals() -> None:
        """SIGTERM/SIGHUP (closing the window) must run `finally` too: an orphaned
        bridge keeps consuming this agent's mailbox into a dead pipe."""
        def bye(signum, frame):
            raise SystemExit(128 + signum)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, bye)
            except ValueError:   # not the main thread (tests)
                pass

    def run(self) -> int:
        self._exit_on_signals()
        if self.bridge_argv:
            self.bridge = subprocess.Popen(self.bridge_argv, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
            threading.Thread(target=self._read_bridge, daemon=True).start()
        threading.Thread(target=self._read_stdin, daemon=True).start()
        try:
            while True:
                src, payload = self.inbox.get()
                if src == "eof":
                    return 0
                if src == "terminal":
                    if payload in ("/exit", "/quit"):
                        return 0
                    turn = Turn(payload)
                else:
                    t = envelope_to_turn(payload, self.agent.name)
                    if t == "selftest":
                        _sh([self.las, "speak", "OK", "--name", self.agent.name])
                        continue
                    if t is None:
                        if payload.get("kind") == "title-request":
                            self.answer_title_request(payload)
                        elif payload.get("kind") == "cc":
                            self.say(f"[cc de {payload.get('from')}] {payload.get('text')}")
                        continue
                    turn = t
                    self.say(f"\n[{turn.sender or 'mic'}] {turn.text}")
                self.last_topic = turn.text
                try:
                    answer = self.agent.handle(turn)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    answer = f"(local model unavailable: {exc})"
                self.deliver(turn, answer)
        except KeyboardInterrupt:
            return 130
        finally:
            if self.bridge:
                self.bridge.terminate()
                try:
                    self.bridge.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.bridge.kill()
