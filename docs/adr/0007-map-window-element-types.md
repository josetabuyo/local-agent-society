# ADR 0007 — The Map window (`las map`) and element types

Status: **Accepted, in progress** (2026-11-10). Requested by José by mic, same day.

Done so far: the `las map` CLI + API for elements, the type registry (`renderer/map-model.js`) and the read-only Map window.

## Context

The widget's 👥 button (the right-most one) opens the society drawer: a List and a 2D Panel of
mini widgets drawn from one model, `widget-electron/renderer/society-model.js`. That model knows
three fixed kinds: `terminal`, `command` and `friend`, each with a hard-coded action list.

José wants this to grow into a separate window, **Map**, made of **domains**: one per screen or
monitor. Each screen has a theme, and the widget is how we work the computer for that theme. Map
holds many *types* of element:

- terminals, one type per runtime: Claude Code, Claude Relay, Codex, shell
- commands (`las <command…>`, ADR 0006)
- friends (las-friends)
- URLs (new)
- GitHub repositories: a local folder plus `gh` data (new)
- more types later

Every type shares common behaviour (close, focus, type to it, dictate to it). Each also brings its
own icons and actions, such as a repo's *refresh* or *open PRs*. A repo should also be drivable by
voice: the dictation goes through a tool-specialist bot (`pulpo gh`, like `pulpo las`) that turns
words into the tool's commands.

## Decision

### 1. An element-type registry replaces the fixed kinds

Each type contributes one entry, modelled on tldraw's `ShapeUtil` and Home Assistant's
`customCards`:

```js
LasMap.registerType({
  type: 'repo',                    // stable id; also the visibility key
  label: 'GitHub repos', icon: '…',
  group: 'tools',                  // display grouping: sessions | agents | tools | links
  items(world) { … },              // builds items of this type from backend data
  face(item) { … },                // what the mini widget shows (label, detail, badge)
  actions: [ … ],                  // type-specific actions (below)
});
```

The host owns the shared parts:

- geometry, layout and drag (the current `layout`/`clamp`)
- selection
- colors (`chipColors`)
- persistence
- the **base actions** every type gets: `exit`, `keyboard`, `mic`, `find` when it has a window

A type only declares its data and its face.

### 2. Actions are data, in one table

```js
{ id: 'refresh', title: 'Refresh from gh', icon: '↻',
  when: (item) => item.hasGh,      // VS Code-style enablement
  args: { /* JSON Schema */ },
  risk: 'read' | 'write' | 'destructive',
  run: (item, args) => … }
```

Three consumers read this one table: the tile's buttons, a command palette, and the tool list a
specialist bot is given. `describeAction` today is the first step toward it. Its tooltip and
enabled logic become `title` and `when`.

### 3. The Map window — `las map`

Map is its own `BrowserWindow`, opened by 👥 or by `las map [name]` (named like `las widget`, José 2026-11-10: LAS exists so we never get lost while multitasking), with the same "reopen, not focus" rule as every
widget window. It does not replace the drawer until the window is at parity.

**Look (José, 2026-11-10):** the society panel's 2D board in a widget of its own. It has the
agent's color glass and the same mini widgets, and they are draggable. It is one board, with no
grouping and no per-type filter. The only display choice is **Canvas / List**, at the top right.
Every mini widget has a ✕, shown on hover:
- a terminal or command closes, with two clicks;
- a friend's widget closes;
- a repo or URL leaves the map.

A click on a URL or repo tile opens its link.

(A first draft had a "Display" popover with group-by, type chips and "show empty types". José
removed all three: the map must look and behave like the panel.)

### 4. Voice to a tile goes through a specialist, and LAS enforces the risk

Dictating to a tile whose type declares a specialist works like this:

1. The text goes to the specialist (`pulpo gh --json "<dictation>"`, cwd = the repo folder). LAS
   connects that specialist and knows nothing about what thinks inside it.
2. The answer comes back as the contract `{ok, answer, actions, model}` plus an optional
   `confirm_needed: {id, command, why}`.
3. What runs depends on the agent's **security mode**: `security_mode` in its `.las-agent.json`, set
   in the widget's settings ("Security") or with `las agent security dangerous|safe` (José,
   2026-11-10). There are two modes for now:
   - **`dangerous` (the default), made for voice:** no popup for anything that creates, adds,
     changes or closes. That covers:
     - closing a terminal, stopping a command, unlinking a friend, taking an element off the map;
     - a specialist's writes: a new issue, a comment, a merge, closing an issue.

     What happens is told in the widget's log, as conversation: the dictation, what ran, the answer.
     The single exception is **deleting**, which cannot be undone. A specialist's deletion still
     stops on the popup: a repo or release delete, a branch delete, a force push, `api -X DELETE`.
   - **`safe`:** every one of those stops on a popup in the window, showing what will happen, and
     runs only when it is accepted (Enter / Accept). Esc, Cancel or a click outside drops it. For a
     specialist, the popup shows the literal command from `confirm_needed`, and the action is re-run
     with `--confirm <id>`.

   The old two-click confirm on ✕/🚪 is gone: the mode decides.

LAS passes the mode to the specialist on every call: `dangerous` → `--confirm-policy delete` (only
deletions come back as `confirm_needed`), `safe` → `--confirm-policy write` (every write and every
deletion does). The specialist still tags every action with its `risk`, in both modes,
because that tag drives the stop in `safe`. In both modes it never obeys instructions found inside the data it
reads, such as a PR body or an issue title. The risk is enforced in LAS and in the specialist's
CliSpec, never trusted from the model (MCP annotations are hints, not security). `pulpo las` stays the first ally and can later intercept
every mic dictation. The specialist slot is open to other engines through the same contract.

## Consequences

- `KIND_ICONS` / `ACTIONS_BY_KIND` / `describeAction` move into per-type registrations. The current
  three kinds are re-expressed as types first, with no visible change. The tests in
  `widget-electron/test/` must pass unchanged.
- URL and repo are the first new types. Repo needs a backend endpoint that reads `gh` for a folder
  (cached; refresh is the `refresh` action).
- `pulpo gh` is built by Pulpo and measured by LocalModels (`local-models/agent_eval/suites/gh.yaml`),
  with the same method as `pulpo las`.

## Phases

1. Registry refactor: the three existing kinds become types (no UI change).
2. Map window opened by 👥, with the Display popover and type chips.
3. URL type.
4. Repo type: backend gh reader, refresh, open PRs.
5. Voice through `pulpo gh`, with confirmation cards.

## Adding elements — CLI first, the window reads (José, 2026-11-10)

The window is for reading. Elements are added by command, and every interface calls the same
backend endpoint, so the CLI, the API and any later "+" button can never disagree:

```bash
las map                       # open the Map window (the agent in the cwd); recreated on this Space
las map open NAME             # someone else's
las map list                  # the added elements, in the terminal
las map add repo [PATH] [--label L]
las map add url URL [--label L]
las map remove ID             # repo:<path> / url:<url>, as `las map list` prints it
```

`GET/POST/DELETE /agents/{name}/map` stores them as `map` in the agent's `.las-agent.json`. A repo
inside the agent's folder is kept relative to it, so moving the folder keeps the map. Sessions and
friends are on the map too, but they are derived, never added here. An add button in the window is
not planned: probably never.

## Irreversible actions in `dangerous` — decided

José, 2026-11-10: in `dangerous`, deletions ask and nothing else does. Creating and adding never ask.

## Open questions (José)

None right now.
