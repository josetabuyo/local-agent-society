# ADR 0008 — Voice sessions: Claude or Codex with no terminal

Status: accepted (2026-11-27) — `cli/voice_session.py`, `las voice-turn`, `POST /agents/{name}/sessions/voice`

## Context

`las <command…>` (ADR 0006) already connects any program with no terminal, but
each message starts from scratch: good for `echo`, useless for a conversation.
The human wants to use Claude or Codex *only by voice*: dictate a task, hear the
answer, dictate the reply — no terminal anywhere — from every entry point.

## Decision

```
las claude --headless        # personal account
las claudeRelay --headless   # second account (~/.claude-relay)
las codex --headless
```

connect a detached session (ADR 0006) of the agent here, runtime `claude` /
`claudeRelay` / `codex`, title "sesión de voz, sin terminal", and make it the
default — the mic talks to it now. Its command is `las voice-turn RUNTIME CONV`:
every message runs ONE non-interactive turn of the same conversation `CONV`:

The runtime's own conversation id lives in `~/.las/voice/CONV.thread`, the
same way for both: no file → a new conversation (Claude gets a fresh
`--session-id`, Codex names its thread in the first `thread.started` event)
and the id is written; a file → `claude -p --resume ID` / `codex exec resume
ID`. Claude runs with `--permission-mode bypassPermissions`, Codex with
`--yolo` — nobody is there to approve.

- **Resume** an existing conversation, closed or started in a terminal:
  `las claude --headless --resume ID` (`-r`, `--resume` alone or `-c` = this
  folder's latest), `las codex --headless resume ID|--last`; the endpoint takes
  `{"resume": "ID" | "--last"}`. It only pre-writes the `.thread` file. Don't
  resume a conversation that is still open in a terminal: both would write it.
- **Clear**: dictate "nueva conversación" / "/clear" (also "borrar la
  conversación", "new conversation") — the file is deleted, nothing runs, the
  answer is "Listo, conversación nueva.", and the next turn starts afresh.

Both get the same appended instructions (Claude `--append-system-prompt`, Codex
`-c developer_instructions=`): voice only, answer in the agent's language in a
few plain spoken sentences, ask one question when a decision is needed, and skip
every `/las-agent` session-start step. The final message is the answer
(`bridge/src/answer.js`): spoken for the mic/phone, sent back to an agent. A
failed or timed-out turn (`LAS_VOICE_TURN_TIMEOUT`, 30 min) is *said*, never
silent.

`LAS_VOICE_SESSION=1` is in every turn's environment: the end-of-turn hooks
(`cli/turn_hook.py`) stay out — the answer already is the closing report.

**Entry points**: the CLI above; `POST /agents/{name}/sessions/voice
{"runtime", "resume"?}` (runs `las <runtime> --headless --no-widget` in the
agent's folder through the login shell) for the widget — 🎙 Claude / 🎙 Codex
in the 👥 drawer, and in the ⧉ button's hold menu next to Terminal and Folder
(reorderable: one can be the plain-click default) —, the phone and other agents. ✕ in 👥 closes it, 📄 opens its log.

## Consequences

- A turn is silent until it finishes; long tasks mean a long wait for the answer.
- Closing a voice session keeps its conversation: reopen it headless with
  `--resume`, or in a terminal with `las claude --resume ID` / `las codex resume ID`
  (the id is in the session's log line and in `~/.las/voice/`).
- Not supervised across reboots (same as ADR 0006).
