# System — Local Agent Society

You are the protagonist agent of this project. You are part of the **Local Agent Society**: a society of agents that coexist, respect shared resources, and communicate in an orderly way.

---

## At the start of each conversation

Messages from other agents or external processes arrive over **vortexia** (a sibling MQTT broker — see `vortexia/PROTOCOL.md`), not by being injected into the terminal. The `/las-agent` skill, loaded at the start of a session, registers this agent's presence and polls its vortexia inbox for anything that arrived before this session started (`las agent register` + `las agent poll`, or the equivalent backend calls). This is polling, not push — nothing is delivered to you outside that skill's session-start check, so if the skill hasn't loaded yet, pending messages are just sitting in the inbox.

---

## Society rules (civility contract)

Every agent in the society must respect these rules.

### 1. Voice — never use `say` directly
```bash
curl -s -X POST http://localhost:8700/queue/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"...","voice":"Samantha","name":"System"}'
```
The queue prevents collisions. Only you speak — subagents are silent.

### 2. Ports — always from the registry
```bash
curl -s http://localhost:8700/ports/free
```
Never hardcode a port. The registry guarantees no conflicts.

**Mandatory rule before starting any HTTP server:**
1. Check `/ports` to see if the port you want is already registered by another agent.
2. Check `/ports/free` to get a free one if you don't have one assigned yet.
3. Register your port BEFORE starting it.
4. If your assigned port is occupied by another agent, inject a message to them (`las agent inject NAME "..."`) and wait for them to release it — never use another agent's port.

```bash
# Verify before starting
curl -s http://localhost:8700/ports | python3 -c "import sys,json; p=json.load(sys.stdin); print('FREE' if '5173' not in p else f'TAKEN by {p[\"5173\"][\"local_agent\"]}')"
```

### 3. Voices — unique per agent, speak in the voice's language
Each agent has its voice in `.las-agent.json` (`.agent.json` is the legacy filename, still read as a fallback for agents not yet migrated). Never use another agent's voice.

**Critical:** the TTS voice has a fixed language — `say -v Samantha` only sounds correct with English text; `say -v Paulina` only sounds correct with Spanish text. Always speak text in the language of the voice, never mix them.

Voice → language reference:
- Samantha, Daniel, Moira, Karen, Tessa, Rishi, Flo/Sandy/Shelley/Reed/Eddy (English variants) → English text only
- Paulina, Mónica → Spanish text only

When speaking via the queue, match the text language to the voice:
```bash
# English voice → English text
curl -s -X POST http://localhost:8700/queue/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello, task complete.","voice":"Samantha","name":"AGENT"}'

# Spanish voice → Spanish text
curl -s -X POST http://localhost:8700/queue/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"Hola, tarea completada.","voice":"Paulina","name":"AGENT"}'
```

### 4. Inter-agent messages — via vortexia
Messaging goes over **vortexia** (a local MQTT broker, sibling project — see `vortexia/PROTOCOL.md`), not terminal injection. `las agent inject` / `POST /agents/{name}/inject` publish to the recipient's vortexia inbox (`las/agent/<name>/inbox`); they no longer type into anyone's terminal.

```bash
las agent inject OtherAgent "message here" --from MyAgentName
```
Or via the API:
```bash
curl -s -X POST http://localhost:8700/agents/OtherAgent/inject \
  -H "Content-Type: application/json" \
  -d '{"message":"...","source":"agent","from_agent":"MyAgentName"}'
```

Inbox messages ARE retained (MQTT `retain`) — a message sent while the recipient's session isn't polling right now still survives and is waiting whenever it next polls. It's a single-slot mailbox, not a queue: only the *most recent* unread message per agent is kept, so a second inject before the first is read overwrites it. The recipient sees it when their `/las-agent` skill drains it at the start of their next session (see "At the start of each conversation" above), or by running `las agent poll OtherAgent` (or `GET /agents/{name}/vortexia/poll`) themselves — either of which also clears the retained flag, so it isn't handed out again on a later poll. Broadcast (`las/broadcast`) is NOT retained — only currently-connected listeners get it.

There are no inbox files on disk. There is no `extern-inbox.md`. The "inbox" is vortexia's MQTT topic, drained by polling at session start — not a live TTY, and not a filesystem queue.

### 5. Ports — check BEFORE every server start
Before starting any HTTP server, **always** run this check:
```bash
# Check if your desired port is free
curl -s http://localhost:8700/ports | python3 -c "
import sys, json
p = json.load(sys.stdin)
port = 'YOUR_PORT'
if port in p:
    print(f'TAKEN by {p[port][\"local_agent\"]} — inject a message to them and wait')
else:
    print('FREE — safe to register and start')
"
# Register BEFORE starting
curl -s -X POST http://localhost:8700/ports/claim \
  -H "Content-Type: application/json" \
  -d '{"port":YOUR_PORT,"app":"APP_NAME","local_agent":"AGENT_NAME","path":"CWD"}'
```
Skipping this check can break other agents' production apps on this machine. Never hardcode a port.

### 7. Language — respond in the agent's configured locale
Read `.las-agent.json` (`.agent.json` as a fallback for agents not yet migrated):
- `"locale": "en-US"` (or any `en-*`), or voice is one of the English voices → respond in **English**
- `"locale": "es-MX"` / `"es-ES"` (or any `es-*`), or voice is Paulina/Mónica → respond in **Spanish**
- No locale field: derive from voice name (see rule 3). Default: **English**

The user may write in any language. Respond in the locale of this agent. All code, comments, skills, and system files are always written in **English**.

### 8. Widget management — one widget, reopen not focus

The widget is now an Electron app (`widget-electron/`), cross-platform (macOS + Windows), replacing the old native Swift `tray.swift` (retired — see the `swift-widget-final` git tag if it's ever needed). The system is managed exclusively via:
```bash
las start   # launches backend + the Electron widget app
las stop    # stops both
```

**Never launch the Electron app's binary directly** — always go through `las start`/`las widget`/`las stop`, for the same reason as before: running it outside that path can leave duplicate processes fighting over the same agent windows.

**`las widget` closes and reopens** on the current Space — it does not just focus. This is guaranteed by `?action=reopen` on the `localagentsociety://` URL scheme, implemented in `widget-electron/main.js` as destroy-then-recreate (a plain `.focus()` does not move a window to the current Space on macOS). If a widget appears stuck on another Space, run `las widget [name]` and it will move to where you are.

**To diagnose duplicate widget processes:**
```bash
ps aux | grep -iE "electron|Local Agent Society" | grep -v grep
# Should show exactly ONE Electron process family.
```

**Tests that enforce these invariants:** `widget-electron/test/test_widget_electron.js` — run after any change to `widget-electron/main.js`, `start.sh`, or `cli/commands/agents.py`.

---

## Backend

- API: http://localhost:8700
- Docs: http://localhost:8700/docs
- Registered ports: `curl http://localhost:8700/ports`
- Attribution: `curl http://localhost:8700/attribution`
