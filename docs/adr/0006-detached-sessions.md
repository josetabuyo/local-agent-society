# ADR 0006 — `las <command…>`: any command connected to an agent, no terminal

Status: accepted (2026-11-03) — `cli/connected.py`, `bridge/src/sinks/exec.js`, `bridge/src/answer.js`

## Context

LAS has no AI of its own (the 🧭 general mic, the scope router and `las local`
are gone). What it adds is a way to connect ANY command to an agent as one more
session next to `claude`, `codex` and `shell` (docs/adr/0004) — with no
terminal. Any CLI qualifies — a bot, a script, plain `echo`; LAS is coupled to none of them.
LAS takes no responsibility for whatever thinks inside the command.

## Decision — one case, the simplest

```
las echo Recibido:
```

typed in the agent's folder (the widget's ⧉ opens a terminal there). When the
first word is not a `las` subcommand but a program on PATH, LAS registers a
session of that agent and returns — the terminal is free again:

- **runtime** = the command's first word (`echo`), **title** = the command line;
- **every message** to the session runs the command ONCE, a new process, with
  the text as ONE more argument: `echo Recibido: '<what the mic heard>'`. Stdin is
  empty; the env carries `LAS_AGENT`, `LAS_AGENT_DIR`, `LAS_FROM`,
  `LAS_SOURCE` (`human` = the mic), `LAS_KIND`, `LAS_TEXT`, `LAS_MSG_ID`,
  `LAS_LOCALE`. Only `message`/`command` kinds run it;
- **its stdout is the answer** (`bridge/src/answer.js`): spoken in the agent's
  voice when it answers the mic — so it also lands in the widget's history —,
  sent back when another agent asked, never sent to its own agent (that
  mailbox may be this very session: an echo would loop forever);
- it **never takes the default session**: the mic stays where it was until the
  human picks the row in 👥 (unless it is the agent's only session);
- **close**: ✕ in 👥 (the backend SIGTERMs the bridge); **log**: 📄 in 👥
  (`~/.las/logs/sessions/<agent>-<stamp>.log`).

`las attach <command…>` is the same in the foreground, for when the human
wants to watch each run: Ctrl-C closes it; ⌖/✕ work as for any terminal.

Commands are stateless by design: each message starts from scratch.

## Consequences

- One sink (`exec`), one rule for answers; nothing to configure.
- Windows quoting is handled (`quoteArg`), but `las <command…>` is untested there.
- Not supervised across reboots (ADR 0003's single supervisor).
- A long-lived variant (one process for every message) is deliberately NOT
  implemented until a case needs it (LEAN).
