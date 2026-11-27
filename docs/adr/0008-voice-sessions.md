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

- **Claude**: `claude -p --session-id CONV` the first time, `--resume CONV`
  after (the transcript file under `<config>/projects/*/CONV.jsonl` tells which),
  `--permission-mode bypassPermissions` — nobody is there to approve.
- **Codex**: `codex exec --json --yolo`; the `thread.started` id is kept in
  `~/.las/voice/CONV.thread` and later turns run `codex exec resume THREAD`.

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
{"runtime"}` (runs `las <runtime> --headless --no-widget` in the agent's
folder through the login shell) for the widget's 👥 drawer (🎙 Claude / 🎙
Codex), the phone and other agents. ✕ in 👥 closes it, 📄 opens its log.

## Consequences

- A turn is silent until it finishes; long tasks mean a long wait for the answer.
- One conversation per voice session; closing it ends the conversation (it can
  still be opened in a terminal: `las claude --resume CONV`, `las codex resume THREAD`).
- Not supervised across reboots (same as ADR 0006).
