# ADR 0005 — Nested mailboxes: an agent's sessions are its children queues

## Status

Accepted (2026-09-30). Applied in the same change. Extends ADR 0004 phase 2
(connected sessions) and ADR 0001 (scope ladder).

## Context

Since ADR 0004 phase 2 an agent can have several runtimes attached at once
— a Claude (`las claude`), a Codex (`las codex`), a plain shell (`las
shell`) — each a *session* with its own mailbox topic on vortexia. The
sender could pick one (`send --session`, `--all-sessions`) and the widget
mic could too, through a press-and-hold menu on the mic button whose choice
lived in a per-window Electron pref.

Three things were wrong with that:

1. **The choice belonged to the wrong owner.** Where a message to an agent
   lands among its children is that agent's business, not the sender's and
   not one widget window's. A `las agent send --to Robo` from another agent
   and a mic dictation from the widget must land in the same place, decided
   once, and survive the widget being restarted or opened on another
   machine. So it has to live in the agent's own file, `.las-agent.json`.
2. **The mic button was doing two jobs.** Click to dictate, hold for a
   session list. And the button next to it — the ⌖ focus/scope button
   (focus a TTY, link a TTY) — no longer had one: delivery is vortexia, not
   a TTY (ADR 0004). One button too many, one job in the wrong place.
3. **Sessions were invisible to routing.** Vortexia's scope ladder (ADR
   0001, `vortexia/docs/vxia-scope-ladder.md`) describes *agents*; nothing
   described what each *session* of an agent is for. A shell only runs
   `kind: "command"` (`ShellSink`), a Claude understands prose — a router
   that reaches the agent has no way to know which child to pick.

The user's framing: *the micro (agent → sessions) and the macro (society →
agents) should be one rule — nested queues.*

## Decision

**One rule at every level.** A routable node has a mailbox, a scope
descriptor, and children; each child is again such a node. A plain address
reaches the node's *default* child (the last one used), `all` fans out to
every child, a named child gets only that one. The node itself decides
where an unqualified message goes; the sender may override.

| Level | Node | Children | Fan-out | Default child | Descriptor |
|---|---|---|---|---|---|
| Society | environment (a Mac) | agents | `--scope` broadcast, `--children` (folder hierarchy) | — | agent scope ladder (ADR 0001) |
| Agent | `las/agent/<name>/inbox` | sessions (`las/agent/<name>/sessions/<sid>/inbox`) | `sessions.target: all` / `--all-sessions` | last used (`default-session`) | `sessions.runtimes.<runtime>` |

Concretely:

- **`.las-agent.json` gains a `sessions` section** (`cli/agent_config.py`
  is the single schema for CLI and backend):

  ```json
  "sessions": {
    "target": "default",
    "cc_default": false,
    "runtimes": {
      "claude": {"intelligent": true,  "accepts": ["message", "command"], "scope": "Claude Code session: ..."},
      "codex":  {"intelligent": true,  "accepts": ["message", "command"], "scope": "Codex TUI: ..."},
      "shell":  {"intelligent": false, "accepts": ["command"],            "scope": "plain shell: literal commands only, ..."}
    }
  }
  ```

  `target` is where a plain send and the widget mic land: `default` (the
  last-used session, through the agent mailbox its bridge holds), `all`,
  a runtime name or a session id. `cc_default` hands the default session
  a for-the-record copy (`kind: "cc"`) whenever a message went to another
  child — so the intelligent session keeps track of what the human told
  the shell. `runtimes` is one descriptor per runtime kind: the same idea
  as the agent's scope ladder, one level down, for a router to match on.
- **The backend applies the rule** (`_resolve_targets` in
  `backend/main.py`): an explicit sender choice wins (and a choice nothing
  is connected for is a 404, as before); otherwise the recipient's
  `sessions.target`. A configured target that is not connected falls back
  to the agent mailbox — queued by the broker, never lost — and the
  response says so (`fallback_from`). `GET/PATCH /agents/{name}/config`
  read and merge the file (the backend knows every agent's path; nothing
  else goes looking for it). `GET /agents/{name}/sessions` carries each
  session's descriptor and the agent's `target`/`cc_default`.
- **CLI**: `las agent target [default|all|<runtime>|<sid>] [--cc/--no-cc]`
  shows or sets the choice; `las agent send --cc` asks for the copy on one
  send; `las agent sessions` marks non-intelligent sessions. `las agent
  new` writes the section with its defaults.
- **Widget**: the ⌖ focus/scope button, its TTY picker and the
  `focus`/`ttys`/`pin-tty` IPC are gone. A 👥 **children** button takes its
  slot: click, hold or right-click lists the sessions (last used / all /
  each one, with its scope as a tooltip) and the cc toggle; picking a row
  writes `sessions.target` through the backend. The mic sends with no
  target of its own — the backend routes it — so the CLI and the widget
  can never disagree. Settings keeps "Dictation goes to" and gains "Copy
  last-used session", bound to the same write. The widget also watches the
  session inboxes as a viewer, so a dictation aimed at the shell still
  shows in its log; `cc` copies are not shown (the original already is).
- **Kinds follow the child's contract.** A child whose descriptor accepts
  nothing but commands (the shell) is handed whatever it gets *as* a
  command (`kind: "command"`), so choosing the shell means "run what I
  say" — a wrong sentence is just a failed command, as asked. A sender
  can also mark one explicitly (`las agent send --command`, `kind` on
  `/agents/send`), e.g. to make a Claude session run something.
- **Bridge**: `kind: "cc"` is a known kind. Only the Claude channel ever
  receives it (its instructions say: note it, no action, no reply, no
  closing report); every other sink — Codex's TUI, `las shell`, `--exec`
  — drops it in the pipeline, because typed into Codex or handed to a
  shell it would be acted on. `ShellSink` additionally refuses to run a
  `cc` even under `--all`.
- **A broken `.las-agent.json` is never overwritten.** `PATCH /config`
  answers 409 when the file exists but is not valid JSON, instead of
  replacing it with the patch alone; reads stay tolerant (a typo in one
  agent's file never takes a send or a session register down).

## What a communication-systems expert would flag (and what we did)

- **MQTT topics already are a nested queue hierarchy.** The rule above is
  the topic tree: `las/agent/<name>/inbox` → `.../sessions/<sid>/inbox`.
  Nothing new is invented on the broker; the addition is *who decides* the
  hop (the node, via its file) and *where that decision is applied* (the
  owning backend). Resolution of everything after the agent name belongs
  to the environment that holds the session registry, so vortex-relay
  never needs to know sessions — a cross-machine `Name@env` message is
  resolved into a child only after it lands. That is the property that
  makes the rule the same at both levels: each level resolves its own
  children.
- **Persistent session mailboxes for dead sessions leak.** Every session
  inbox is an MQTT persistent session (`las-agent-<name>-<sid>`); when a
  terminal closes, its queue lingers until the broker's 30-day TTL. The
  backend prunes dead pids and never publishes into a session nobody
  holds, but the broker-side session survives. Asked of Vortexia (owner of
  the broker): a way to drop a mailbox by client id so the backend can
  purge on `DELETE /sessions/<sid>`. Until then it is bounded (cap 500,
  TTL) rather than fixed.
- **Fan-out to a non-intelligent child is safe but noisy.** `all` sends
  prose to the shell too; `ShellSink` only runs `kind: "command"`, so it
  is printed, never executed. Acceptable, and exactly why `accepts` exists
  in the descriptor: ADR 0004 phase 3's first-decision layer can use it
  to send prose only where prose is understood. Not applied automatically
  in this change — the human picks, as asked.
- **A configured target must never lose a message.** A pinned `shell` with
  no shell open would otherwise 404 every dictation. Fallback to the agent
  mailbox (queued for the default session) with an explicit
  `fallback_from` is the only safe choice; the widget logs it, the CLI
  prints it.
- **Two sources of truth would drift.** The Electron pref `micTarget` was
  removed rather than mirrored: one file, read by everyone. The widget and
  the CLI also write the same *vocabulary*: a runtime name (`shell`),
  which survives that terminal being reopened with a new session id; a
  session id only when two sessions of one runtime are connected.
- **The widget must never republish.** Its send goes through the backend;
  a direct inbox publish happens only when the backend could not be
  reached at all — any HTTP answer, even a 500, means it may already have
  published, and a hung backend is a bounded timeout, not a duplicate.
- **`las agent new` writes the full descriptors.** Deliberately (the user
  wants the list in the file, editable per agent): the file is the truth
  and `DEFAULT_RUNTIMES` only fills what a file leaves out — a refined
  default does not reach a file that already states its own.

## What was asked of Vortexia (protocol owner)

Sent over vortexia on 2026-09-30, to be reflected in `vortexia/PROTOCOL.md`
by its own agent (see `feedback_vortexia_ownership_handoff`): document the
session topics and `default-session` as a "Sessions (nested mailboxes)"
section; the address grammar `Name[@env][/<sid>|/<runtime>|/*]` with
resolution at the owning environment; an optional `children` array on
`scope-reply` so progressive-depth matching can descend from agent to
session; a way to drop a dead session mailbox; and whether the JS client
should expose viewer subscriptions instead of the widget touching
`mqttClient` directly.

## Consequences

- A plain `send --to Name` now honors the recipient's `sessions.target`.
  Out of the box that is `default`, so nothing changes for existing agents
  until they choose otherwise.
- `focus`/`ttys`/`pin-tty` backend endpoints stay for `las agent focus`;
  only the widget stopped using them.
- Tests: `tests/test_agent_config.py`, additions in `tests/test_sessions.py`
  and `tests/test_cli_sessions.py`, the bridge's envelope/channel tests,
  and the widget's children-button tests replacing the focus/mic-target
  ones.
