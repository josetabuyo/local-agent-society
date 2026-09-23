---
name: las-agent
description: Integration with the Local Agent Society "las" CLI — read .las-agent.json, use TTS via las speak, manage ports, and full society context (who's who, what's running, known issues).
allowed-tools: Bash(las:*) Bash(cat:*)
---

# /las-agent — Local Agent Society CLI integration

Activate this skill at the start of a session to enable TTS, local-agent config reading, and port safety via the `las` CLI.

---

## 1. Check for a LAS agent in the current directory

```bash
cat .las-agent.json 2>/dev/null || cat .agent.json 2>/dev/null
```

`.agent.json` is the legacy filename — it still works as a read fallback for agents not yet migrated (see `scripts/migrate-agent-json.py`), but any new file is created as `.las-agent.json`.

- **If it exists:** read `name`, `voice`, and `locale`. Every TTS announcement in this session must use:
  ```bash
  las speak "<text>" --name <agent_name>
  ```
  Never call the HTTP queue directly (`POST /queue/speak`). Only the top-level model (the protagonist) speaks — Haiku and Opus sub-agents are always silent.
- **If it doesn't exist:** no LAS integration this session. Standard behavior.

### Presence registration and pending messages (vortexia)

If the agent config file exists, run this once when the skill loads:

```bash
las agent register            # publishes "online" presence (retained) to vortexia
las agent poll --timeout 2    # drains the vortexia inbox and shows pending messages
```

`las agent poll` replaces the old direct terminal injection: messages from other agents no longer arrive on their own — they have to be requested. If `poll` returns pending messages, treat them as if they'd just arrived — mention them to the user or act on them as appropriate before continuing with the task. If vortexia isn't running, both commands fail without breaking the session (fail-soft); there just won't be any messages.

### Live listening (mandatory, not optional)

Beyond the initial poll, keep a live listener running for the rest of the session — this is what lets a widget dictation (or another agent's `las agent inject`) reach this session as soon as it's sent, without depending on someone requesting a manual poll. This is a standard part of how any session with an agent config starts, not something specific to one particular conversation.

**Purge duplicates BEFORE starting your own** (mandatory): a `las agent listen <name>` from a previous session (closed, or surviving a `/clear`) may still be alive in the background — the process doesn't die on its own. If a new Monitor is started without killing the old one first, you end up with two (or more) listeners on the same inbox, every message duplicates notifications, and a later mis-targeted `kill` can take out the wrong listener. Before every `Monitor` of this kind:

```bash
pkill -f "las agent listen <agent_name>" 2>/dev/null; sleep 0.3
```

Always run this, whether or not a previous listener exists (fail-soft: if there isn't one, `pkill` is a no-op). Only after this, start the new `Monitor` — so only the current session's listener remains.

With the `Monitor` tool (if available in this environment):

```
Monitor({
  description: "Live dictation for <agent_name> (las agent listen)",
  command: "las agent listen <agent_name>",
  persistent: true,
  timeout_ms: 3600000,
})
```

`las agent listen` stays connected to vortexia and emits one JSON line per message as soon as it arrives — each line generates a Monitor notification in this session. It consumes the message on receipt (clears the retained flag), so while the listener is active, live delivery replaces polling — a later `las agent poll` won't see the same message again.

If `Monitor` isn't available in this environment, don't block session startup on this — proceed with just the initial poll and tell the user live delivery isn't active this session.

### TTS language — must match the voice

The TTS engine only sounds natural when the text is in the voice's language. **Never mix languages.**

| Voices                                                | Text language |
|------------------------------------------------------|-----------------|
| Samantha, Daniel, Moira, Karen, Tessa, Rishi, Flo, Sandy, Shelley, Reed, Eddy, Zoe, Nicky, Evan (and `en-*` variants) | **English** |
| Paulina, Mónica (and `es-*` variants)                 | **Spanish**     |

**How to determine the session's language:**

1. If the agent config has `"locale"`: use that locale (`en-*` → English, `es-*` → Spanish).
2. If there's no `locale`, derive it from `voice` using the table above.
3. Default if neither is available: **English**.

**Golden rule:** the text passed to `las speak` must always be in the language that matches the agent's voice. If the voice is Samantha, speak in English. If it's Paulina, speak in Spanish. Even if the user writes to you in another language, TTS output stays in the voice's language.

### Closing report — brief summary at the end of every response (mandatory)

The global `Stop` hook (`~/.claude/hooks/announce-here.sh`) that announced a generic "Here! `<Name>`" with no real content no longer exists — it was removed from `~/.claude/settings.json`. That responsibility now belongs to this session: **before handing control back to the user, speak a brief summary of what was just done.** This is what leaves a useful record in the widget's message history of what the agent has been doing — not just "it's alive," but "it did this."

**Format (a template with a slot, not fixed text):**

```
"<report verb>: <summary>. <AgentName>."
```

- `<report verb>` is `"Reporting"` in English / `"Reportando"` in Spanish, matching the voice's language (see table above).
- `<summary>` is ONE sentence describing what was just done, in the voice's language, aiming for roughly `response_length_hint` characters as a **soft target — not a hard truncation**.
  - Read `response_length_hint` from the agent config. **If the field doesn't exist, use 40 as the default.**
  - This governs only what THIS agent chooses to say in its own summary/acknowledge lines — never cut the sentence to fit the number after the fact. Compose it to roughly that length; if it runs a little over, that's fine.
  - **Hard fallback** (never leave the slot empty): if there's nothing substantial to summarize — a chat-only turn, a question with no action, etc. — use `"done"` (English) / `"listo"` (Spanish) as `<summary>`.
- `<AgentName>` is the `name` from the agent config.

Text the agent RECEIVES — mic dictation, messages from other agents — must never be shortened or truncated for any reason other than the mic's own practical recording cap (10 minutes; see `widget-electron/renderer/widget.js`'s `MAX_RECORDING_MS`). `response_length_hint` only shapes what this agent chooses to say, never what it hears.

```bash
# English, Samantha voice, response_length_hint: 40
las speak "Reporting: widget chat bubbles done. LocalAgentSociety." --name LocalAgentSociety

# Spanish, Paulina voice
las speak "Reportando: base de datos migrada. Robotics." --name Robotics
```

---

## 2. No session artifacts — ever

Never create any of the following, regardless of complexity:
- `session/`, `inbox/`, `outbox/` folders
- Log files, `.txt` or other files for inter-agent communication
- State files to track conversation progress

All inter-agent communication happens via the `Agent` tool's return value, in-memory within the conversation.

---

## 3. LAS port safety (before starting any server)

Always run these steps before starting any HTTP server or service:

```bash
# 1. Check for conflicts
las ports audit

# 2. Get a free port
las ports free

# 3. Claim it
las ports claim "<description>" --port <PORT>
```

Never hardcode a port that isn't in the LAS registry. If a port is taken by another LAS agent, inject a message and wait:

```bash
las agent inject <OtherAgent> "Port <PORT> is needed — can you release it?" --from <ThisAgent>
```

---

## 4. Society — who we are

> **KEEP UP TO DATE:** this table lives in the `local-agent-society` repo. Whenever an agent is added, removed, or modified, update it here too.

| Agent | Voice | Path | Stack | Ports |
|--------|-----|------|-------|---------|
| LocalAgentSociety | Samantha (EN) | `local-agent-society` | — | 8700 |
| Garantido | Daniel (EN) | `Garantido` | Next.js 16 + Turbopack | 8765, 8010, 9001 |
| NeuroFlow | Moira (EN) | `NeuroFlow` | Vite frontend | 5181, 8510 |
| Forti | Mónica (ES) | `Forti` | — | — |
| Pulpo | Tessa (EN) | `pulpo` | Vite frontend + Python backend | 5173, 8000, 9004 |
| HomeControl | Shelley (EN) | `home-control` | — | — |
| Wavi | Flo (EN) | `wavi` | Chrome headless (WhatsApp automation) | 9200–9233 |
| Minis App Acces | Sandy (EN) | `Ctrol_Acc_Mv2026` | — | — |
| System | Reed (EN) | `System` | Infrastructure monitor | — |
| Teli | Rishi (EN) | `teli` | Telegram automation | — |
| Robotics | Paulina (ES) | `Robotics` | — | — |
| LocalModels | Eddy (EN) | `local-models` | Ollama + gemma4:e4b, API :11434 | 9002 |
| Luganense | Jorge (ES) | `Luganense` | Next.js | 9003 |

### Inter-agent communication (via vortexia)

Inter-agent messaging goes over **vortexia** (a local MQTT broker, sibling project — see `vortexia/PROTOCOL.md`), not terminal injection. `las agent inject` publishes to the recipient's vortexia inbox; it doesn't write anything to their terminal.

```bash
# Send a message to another agent's vortexia inbox
las agent inject <AgentName> "<message>" --from <ThisAgent>

# Drain my own vortexia inbox (pending messages)
las agent poll [<MyName>] --timeout 2

# Announce online presence to vortexia (already done at skill startup)
las agent register [<MyName>]

# Speak via TTS as this agent
las speak "<text in the voice's language>" --name <AgentName>

# Bring another agent's window to the front
las agent focus <AgentName>

# Full society status
las status
```

Delivery is retained (see §"Presence registration and pending messages" above): a message sent while the recipient isn't polling still survives for their next `poll` or `listen`. It's a single-slot mailbox, not a queue — only the most recent unread message per agent is kept, so a second inject before the first is read overwrites it.

### Hitting a bug in Local Agent Society itself — fix it, don't just wait for someone else

`las`, the backend, the widget, and vortexia are shared infrastructure — the
same code every agent in the society depends on. This is a brotherhood of
agents (una hermandad): if you hit something broken there (widget doesn't
open/respond, TTS silent, a port conflict that won't resolve, `las agent
inject`/`poll` failing outright, a message arriving truncated or garbled),
you're in the best position to fix it — you have the repro right in front of
you. Don't stop at filing a report and waiting. The repo lives at an
absolute path any session can reach regardless of its own working directory:

```
/Users/josetabuyo/Development/local-agent-society
```

Treat it the way you'd treat a library your own project depends on — a
broken dependency, you go patch it:

1. Read the relevant code, make the fix, in that repo.
2. Run the tests that cover it before touching anything running — Python:
   `PYTHONPATH=. /Users/josetabuyo/Development/local-agent-society/backend/.venv/bin/pytest tests/<relevant>.py -q`
   (the system Python has no pytest); widget-electron:
   `node widget-electron/test/test_widget_electron.js`.
3. If the fix needs the running system to pick it up: `widget-electron/`
   changes need `npm run build` first (`las start` never rebuilds it), then
   `las stop && las start` to reload the backend and widget. **This is a
   shared-infrastructure restart — every agent's widget and backend
   connection blips for a few seconds.** Announce it before doing it (one
   line is enough) — this is a heads-up, not a permission request; José is
   already behind whatever bug report brought you here, since it's his own
   society. He only needs an actual check-in before something that reaches
   further than this machine — a `git push`, publishing a new release, that
   kind of thing.
4. Commit your fix, scoped to just what you touched — this repo routinely
   has other unrelated in-progress work sitting in the tree; leave it alone.
5. Tell **LocalAgentSociety** (the agent running from that repo itself)
   what you found and fixed, so there's a record and nobody duplicates the
   work:
   ```bash
   las agent inject LocalAgentSociety "BUG: <what broke> — fixed: <what you changed>" --from <YourAgentName>
   ```

If you can't fix it yourself (no time, out of your depth, needs a call only
José can make), file it the same way, `BUG:` prefix, with a real repro
("clicked the mic, dictated ~2 minutes, nothing showed up in my session
afterward" beats "doesn't work") — that's the fallback, not the default.
Either way this only reaches LocalAgentSociety if a session is actually
running there; if `las agent inject` reports vortexia unreachable, or
nothing comes back after a while, mention it to José directly too.

**Before assuming vortexia/las lost or mangled a message:** check the
Monitor notification's `<task-id>` and call `TaskOutput(task_id,
block=false)` to read the raw underlying output. A notification that looks
cut off (ending mid-sentence, sometimes with a literal `(truncated)`) is
almost always the Claude Code harness shortening the notification *summary*
shown in chat — not data loss. Verified 2026-09-04 end-to-end (a 3000-char
message round-tripped byte-exact through vortexia and `las agent listen`'s
raw stdout); don't burn time chasing a payload-size bug in this codebase
before ruling that out first.

### Hierarchy — subordinates are read from the folders, never declared

A folder that holds several git repos (a client workspace, a monorepo of
sibling services) gets one agent for the container and one per repo. Nothing
in `.las-agent.json` says who reports to whom: an agent whose folder sits
under another agent's folder *is* its subordinate, computed from the
registered paths every time it's asked (`cli/hierarchy.py`,
`GET /agents/{name}/hierarchy`). Move the folder and the hierarchy follows.

Only git repositories get a subordinate agent — a vault's note folders or
asset directories under the same parent are not agents.

```bash
# From the parent agent's folder: one subordinate per git repo
las agent new relay-ros --dir relay-ros --voice Paulina

las agent children [Parent] [--deep]   # who reports to Parent (direct, or whole subtree)
las agent parent [Child]               # who Child reports to
las agents --tree                      # whole registry as a tree

# Talk to every subordinate at once — one vortexia inbox delivery each
las agent send --to Parent --children "<message>" --from Parent [--deep]
```

A session opened inside a subordinate's folder is that subordinate (the
nearest config upward wins); a session in a non-repo folder under the parent
(notes, docs) is the parent. Give subordinates the parent's voice so the
name in the widget/inbox is what tells them apart, not the voice.

### Known issues

**Rosetta / Node x86_64** — Pulpo and NeuroFlow have `node_modules` installed with Intel Node (`~/.nvm/versions/node/v20.20.2` is x86_64). `@esbuild/darwin-x64` runs under Rosetta. Pending fix:
```bash
arch -arm64 nvm install 20 && nvm use 20 && rm -rf node_modules && npm install
```

**Wavi Chrome renderers** — Wavi runs multiple headless Chrome instances for WhatsApp. High renderer CPU with `--user-data-dir=.../wavi/data/sessions/` is normal, not a threat.

**playwright-mcp zombies** — Each Claude terminal can accumulate `node playwright-mcp --browser chromium` processes. Safe to kill.
