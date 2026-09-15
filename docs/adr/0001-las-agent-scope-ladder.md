# ADR 0001: LAS Agent Scope Ladder — Fibonacci-scaled identity descriptions

## Status

Accepted. Defines how LAS's own identity fields feed the bottom of a
Fibonacci-scaled description ladder. **The ladder mechanics themselves — the
`.vxia-scope.<N>.md` file convention, the README-computation rule, and rung
collision handling — are specified in the sibling `vortexia` repo, not
here**, at `vortexia/docs/vxia-scope-ladder.md`. That split is deliberate
(see "Why the file convention lives in vortexia, not here" below): vortexia
is the thing that will scan, embed, and route on this ladder, so it owns the
protocol; LAS is one adopter of it. Automated scanning/warning code and any
vortexia-side routing are future work — see
`vortexia/docs/future-las-agent-scope-router.md`.

## Context

Every LAS agent already has one mandatory identifier: `name` in
`.las-agent.json`, which doubles as the widget's title. `cli/commands/agents.py`
also stubs two optional fields, `short_description` and `long_description`,
added specifically so that "eventually [they] back a vortexia intent-filter
broadcast (who this agent is, what it offers, what it needs)" — the exact
need this ADR formalizes. Both fields have sat empty since; nothing reads or
writes them yet.

The society is growing (13+ agents as of this writing, see the `las-agent`
skill's roster) and vortexia is about to grow a routing layer. Two problems
follow directly from that:

1. **A human or an LLM router needs to find the right agent for a task
   without opening every agent's terminal.** That requires each agent to
   publish *what it's for*, at a level of detail the asker controls — a one-
   line hint, a paragraph, or the full README, matching how much detail
   the query needs.
2. **There's no shared convention for how much text belongs at each level**,
   so today "documenting an agent's scope" means an unbounded free text field
   with no natural stopping point, and no way for tooling to know in advance
   how big a chunk of text it's about to receive.

## Decision

### The ladder

Every LAS agent gets an ordered, strictly increasing ladder of identity
"rungs." Each rung's length cap is a Fibonacci number, and each rung is
strictly more detailed than the one before it. Only rung 0 (`name`) is
mandatory; every rung after it is optional and purely additive — an agent
with just a `name` is fully valid, and so is one that fills every rung up
through a full README.

| Rung | Cap (chars) | Fibonacci? | Where it lives | Spec owner |
|------|------------:|:----------:|----------------|------------|
| 0 | 34 | yes | `name` in `.las-agent.json` (**mandatory** — the widget title) | LAS (this ADR) |
| 1 | 55 | yes | `short_description` in `.las-agent.json` | LAS (this ADR) |
| 2 | 89 | yes | `long_description` in `.las-agent.json` | LAS (this ADR) |
| 3+ | 144, 233, 377, 610, 987, 1597, 2584, next Fibonacci... | yes | `.vxia-scope.<N>.md` | **vortexia** — see `vxia-scope-ladder.md` |
| — | (whatever it measures) | n/a | `README.md`, if the agent has one | **vortexia** — see `vxia-scope-ladder.md` |

The ladder is open-ended upward — there is no fixed "last" rung before
README. New rungs are just the next Fibonacci number; nothing needs to be
renumbered or migrated when one is added. Everything from rung 3 up follows
vortexia's protocol exactly as written there; this ADR doesn't restate it.

### Why 34 is the floor

The floor of the ladder (rung 0, `name`) has to cover the realistic range of
strings a LAS agent's `name` will ever need to hold: it is a title rendered
on a small floating widget, so it is bounded like a person's name, a shop
sign, or a short company name — not like a sentence. 34 is the smallest
Fibonacci number that comfortably covers that range (the widget already
soft-wraps/shrinks longer names via `fitNameToBox`/`smartSplit` in
`widget-electron/renderer/widget.js`, so 34 is a sane target, not a hard
cutoff). All current agent names (`LocalAgentSociety` at 18 chars is the
longest) sit well under it, leaving headroom.

### Why `short_description`/`long_description` map to rungs 1 and 2

These fields already exist in `.las-agent.json` for exactly this purpose
(see Context). Rather than introduce parallel machinery, they *are* rungs 1
(55 chars) and 2 (89 chars) of the ladder, expressed inline in JSON because
they're short enough that a separate file would be overhead. All caps here
are **soft targets**, in the same spirit as `response_length_hint` (see the
`feedback_response_length_soft` memory) — never truncate existing content to
fit; they guide what to *write*, not what to *accept*.

### Rungs 3 and up: adopting vortexia's `.vxia-scope` protocol

Beyond rung 2, further detail moves to files instead of growing the JSON
blob without bound — and that file convention (`.vxia-scope.<N>.md` naming,
how `README.md` slots in by its real measured length, how rung collisions
resolve) is **specified in full in `vortexia/docs/vxia-scope-ladder.md`**,
not restated here. LAS adopts it as-is.

### Why the file convention lives in vortexia, not here

The file naming and its mechanics are not a LAS-specific detail: vortexia is
the thing that will eventually scan, embed, and route on this ladder (see
`vortexia/docs/future-las-agent-scope-router.md`), so vortexia owns that
protocol, the same way it owns its MQTT topic schema in `PROTOCOL.md`. LAS
naming its own file convention (an earlier draft of this ADR called it
`.las-scope.*`) would couple a router-owned protocol to whichever project
happened to adopt it first, and any other project wanting the same
discoverable-by-filename ladder would either have to depend on LAS or
reinvent it. Keeping the file convention vortexia-owned means any project —
not just this one — can publish a `.vxia-scope` ladder that vortexia can
read the same way. LAS's only real contribution is the top three rungs
(`name`/`short_description`/`long_description`), because those already
existed as `.las-agent.json` fields before this ADR — that mapping is
genuinely LAS-specific and stays documented here.

### Explicitly out of scope for this ADR

These are vortexia's concern, not LAS's — see
`vortexia/docs/future-las-agent-scope-router.md` and
`vortexia/docs/vxia-scope-ladder.md`:

- Everything about the `.vxia-scope.<N>.md` file convention itself (naming,
  README computation, collision resolution) — see above.
- A vortexia query protocol for "give me your rung-1 summary" / "a bit more"
  / "the full detail," walking the ladder progressively, including routing a
  message to an agent with no named recipient by matching scope at
  increasing rung depth.
- Embedding-based duplicate/overlap detection between agents whose scope
  ladders describe similar responsibilities, at increasing rung depth.
- Treating a claimed port (from the `/ports` registry) as another queryable
  identity facet of an agent, in the same spirit as the scope ladder.
- Cross-machine vortex-relay (a star topology connecting this machine's
  broker to another machine's).
- A numeric agent ID. One does not exist today (checked: no `id` field
  anywhere in `backend/main.py`'s agent registry) — this ADR is only about
  the *symbolic* (name + scope-ladder) side of identity, which is what a
  human or an LLM router actually searches by. A numeric ID, if it's ever
  added, is an internal bookkeeping key and orthogonal to this ladder.

## Consequences

- **Positive:** `short_description`/`long_description` stop being dead
  fields and get a defined role — the bottom two rungs of a ladder that can
  grow arbitrarily further via vortexia's `.vxia-scope` protocol, without
  LAS needing to design or maintain that part itself.
- **Positive:** README.md participates for free (via vortexia's protocol) —
  no extra authoring effort for agents that already have one.
- **Positive:** the file convention isn't LAS-branded, so any other project
  vortexia might one day route for can adopt the exact same ladder without
  depending on `local-agent-society` at all.
- **Negative / accepted tradeoff:** authors have to actually go count
  characters (or estimate) to decide which `.vxia-scope.<N>.md` to write to.
  This is intentionally left as a manual/skill-assisted judgment call for
  now rather than automated tooling, since no agent currently populates any
  rung past `name` and there's no usage pattern yet to build a scanner
  against.
- **Follow-up work:** the `las-agent` skill (`~/.claude/skills/las-agent/SKILL.md`)
  documents this ladder so any session working with LAS agents applies it
  consistently. Automated scanning, the collision warning, and any
  vortexia-side consumption are tracked as future work in the `vortexia`
  repo, not implemented by this ADR.
