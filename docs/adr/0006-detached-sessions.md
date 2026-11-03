# ADR 0006 — Detached sessions: any command as a runtime, no terminal

Status: accepted (2026-11-03) — implemented: `bridge/src/sinks/proc.js`, `cli/commands/detach.py`

## Context

LAS has no AI of its own. `las local` (qwen + d3) moves out of LAS and becomes
a Pulpo product. What LAS adds instead is a runtime that needs no open
terminal: a **detached process**, a session next to `claude`, `claudeRelay`,
`codex` and `shell` (docs/adr/0004). Open it, close it, read its log. LAS
takes no responsibility for whatever thinks inside it.

Pulpo is the first case, but LAS must accept ANY command that honours the
contract below.

## Decision

`las detach` starts a bridge in the background (no tty, own process group)
with the `proc` sink. The bridge spawns the configured command ONCE and keeps
it running for the life of the session. The bridge stays the only thing that
talks to vortexia; the command only talks stdio.

### The contract a command must honour (v1)

Everything is JSON Lines over stdio — no ports, works the same on macOS,
Windows and Linux.

**Environment** (set by LAS):

| var | value |
|---|---|
| `LAS_CONTRACT` | `1` |
| `LAS_AGENT` | the agent's name |
| `LAS_AGENT_DIR` | the agent's folder (also the working directory) |
| `LAS_SESSION` | this session's id |
| `LAS_LOCALE` | the agent's locale, e.g. `es-AR` |

**stdin — one line per mailbox message:**

```json
{"type":"message","id":"…","from":"José","origin":"human","kind":"message","text":"…","ts":1793709850245}
```

`origin` is `human` (the mic), `agent` or `system`. The command must not
assume anything about `kind` beyond: `message` is a request; `title-request`
asks for a `title` line; anything else may be ignored.

**stdout — one line per thing the command wants LAS to do:**

```json
{"type":"reply","text":"…"}                       // answer the sender of the message being handled
{"type":"reply","to":"OtherAgent","text":"…"}     // or anyone
{"type":"title","text":"Revisando el deploy"}     // the session's title (≈34 chars)
```

A `reply` without `to` goes to the `from` of the most recent message. A reply
addressed to the session's own agent is never sent: that mailbox may be this
very session, and an echo would loop forever. When the message being answered
came from the mic (`origin: "human"`), that reply is SPOKEN in the agent's
voice instead (so it also lands in the widget's history); otherwise it is
only logged. Any
stdout line that is not one of these JSON objects goes to the log, as does
all of stderr. A message is acknowledged to the mailbox once written to stdin.

**Lifecycle:**

- *Alive* = the process is running. No heartbeat.
- *Close* = LAS closes stdin, then sends SIGTERM (Windows: terminate) and,
  after 5 s, kills. The command should exit on stdin EOF.
- *Exit on its own* = the session ends (unregistered, gone from 👥). The exit
  code is logged. LAS does not restart it.

**Log:** LAS owns it, the command doesn't need to know where it is:
`~/.las/logs/sessions/<agent>@<sid>.log` (stderr + non-protocol stdout +
bridge lines). `las detach --log` tails it.

### Where the command comes from

`.las-agent.json` → `"detached": {"command": "…"}`. `las detach --cmd "…"`
sets it. LAS may suggest a default (Pulpo's) but runs whatever is there.

### Surfaces

- `las <command…>` in any terminal: a first word that is no `las` subcommand
  but a program on PATH runs connected, as a terminal session of the agent
  in that folder (`las pulpo agent run`). Like `las codex`: ⌖ finds it, ✕
  hangs it up, it becomes the default when opened.
- `las detach [--cmd CMD]` the same with no terminal · `--each` one run per
  message instead (text on stdin, its stdout is the answer: `pulpo agent`) ·
  `las detach --stop` close · `las detach --log` read.
- `las agent sessions`: runtime = the command's first word (`pulpo`), plus its title.
- A detached one never becomes the default session (opening or messaging a background
  process is not "using" it): the mic and a plain send stay where they were,
  unless it is the agent's only session. Reach it with `--session pulpo`.
- Widget 👥: same row; ✕ closes it; the ⌖ (find terminal) becomes 📄 (open the log).

## Consequences

- One sink, one contract; Pulpo (or anything) plugs in without LAS code.
- No AI, model or flow in LAS.
- Not supervised across reboots in v1 (that's ADR 0003's single supervisor).

## Update 2026-11-03

The widget's 🧭 general mic and LAS's scope router (backend `/route*`,
`cli/scope_router.py`, `las route`) are retired: choosing which terminal hears
something is a task for the agent listening, not a LAS feature. No launcher
button runs a command either — `las <command…>` from any terminal does.

## Update 2026-11-03 (2) — `las <command…>` is detached and per message by default

José: the default is ONE run per message, detached. `las pulpo luganense`
registers a session (runtime `pulpo`, title `pulpo luganense`) and returns;
each message runs `pulpo luganense '<text>'` (the text as one more argument,
stdin empty, `LAS_*` env as for `exec`), and the run's stdout is the answer,
routed by `bridge/src/answer.js` (spoken for the mic, sent to another agent,
never echoed into itself). `las attach <command…>` keeps it in the terminal.
The long-lived JSON-lines contract above stays for `las detach --cmd`.
