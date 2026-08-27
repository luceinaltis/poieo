# Model On The Node Design

**Date:** 2026-08-27
**Status:** Approved for planning
**Relates to:** `2026-08-27-work-graph-view-design.md`, which shipped in #110
and drew the shape of the work. This adds the one fact a drawing cannot
answer: *what is actually doing it.* It is a separate document rather than a
section of that one because that one is built; this is the increment on top.

## Goal

The board can now say what a project does and where it is right now. It cannot
say **what runs it**. A reader looking at `chores ─> review ─> publish` has no
way to tell whether that is three calls to a 3B model on their laptop or three
calls to Opus, and those are very different afternoons.

The answer exists — it is one `resolve()` away — but today it is a file the
reader has to open, in a directory they have to know about, chosen by a key
(`binding:`) on a flow they have to find first.

## 1. Why this does not break principle 1

Logical / physical separation says a graph names a **role**, and a binding maps
roles onto real models. That stays exactly as it is. Nothing here puts a model
id in a graph file.

What changes is who resolves it. Today the runtime resolves at the moment of
the call (`runtime/nodes.py`: `role = spec.role or ctx.graph.default_role`, then
`ctx.binding.resolve(role)`). The board will resolve the same way, at paint
time, and draw the answer.

That distinction is the whole design, and it has a consequence worth stating:
**the resolved model belongs to a flow, not to a graph.** Two flows can run the
same graph file against different bindings — `examples/poieo.yaml` already
runs one graph from two flows, and one of them names its own `binding:`. So
the model is drawn *inside a border*, where a flow's identity already is, and
never on the graph as such.

## 2. Why a model id on screen is not "machinery"

Principle 7 hides mechanism. It is fair to ask whether a model id is mechanism
leaking onto a board that refuses to say "commit".

It is not, for three reasons already written down:

- DESIGN's own description of the board promises that opening a card exposes
  "the flow (graph) on a canvas editor, the trigger schedule, and **the
  role→model mapping (binding)**". The model is a thing this product has always
  intended the user to see. It is one click deep; this brings it up a level.
- Principle 6 — "you can always see what it did" — names *which model answered*
  as one of the things every run must record. It is already in the log. Showing
  it before the run rather than only after is the same fact, earlier.
- Principle 3 is local-first, and the entire reason a user cares is cost and
  speed. `llama3.2:3b` and `claude-opus-5` on the same box mean "free, all
  night" and "watch this". Hiding that is not simplicity; it is a surprise.

What stays hidden is everything *around* the model: providers, base URLs, the
name of the environment variable a key comes from. Those are machinery, and
§5 keeps them off the wire.

## 3. Where it is drawn

**One model, which is the common case.** A project on one binding with
everything on `default` resolves every node the same way. Saying so four times
is noise, so it is said once, on the line that already carries the trigger:

```
   ┌─ chores ───────── daily 2am · llama3.2:3b ─┐
   │  ┌──────┐  ┌─────┐  ┌──────┐  ┌──────┐     │
   │  │ scan │─>│ fix │─>│ test │─>│ gate │     │
   │  └──────┘  └─────┘  └──────┘  └──────┘     │
   └────────────────────────────────────────────┘
```

This line is visible **shut as well as open**, which is the point: ten flows
collapsed is the glance, and "what is running my board" gets answered there.

**More than one model.** The header cannot answer it, so it stops trying and
says how many. Each node that calls a model carries its own, and opening the
border is what reveals which is which:

```
   ┌─ triage ──────────── every 30s · 2 models ─┐
   │  ┌────────────┐  ┌───────┐  ┌────────────┐ │
   │  │  classify  │─>│ route │─>│ draft_bug  │ │
   │  │ llama3.2:3b│  └───────┘  │ claude-opus│ │
   │  └────────────┘             └────────────┘ │
   └────────────────────────────────────────────┘
```

This is the same bargain §1 of the view spec already struck for arrows: shut,
you get the flow's answer; open, you get the node's. The reader learns no new
rule, because there is no rule to learn — they see the right thing either way.

**A router carries nothing.** It calls no model, so it has none, and the gap is
information: it is why branching is free.

## 4. The data it needs

`_shape()` in `web/server.py` gains one field per node:

```python
"model": str | None   # the id this node would call; None if it calls none
```

Three changes follow from that:

- `_shape(graph)` becomes `_shape(flow)` and takes the `LoadedFlow`, because
  the binding lives on the flow (`LoadedFlow.binding`) and the graph does not
  know it exists. The call site already has it: `_shape(runner.flow)`.
- Resolution mirrors the runtime exactly — `flow.binding.resolve(node.role or
  flow.graph.default_role).model` — so the board cannot drift from what the run
  will actually do. Per-node `params` are ignored on purpose: they layer
  generation settings, never a different model.
- Routers get `None` without asking the binding anything.

`NodeShape` in `types.ts` gains the matching `model: string | null`.

**No `role` field.** `_shape`'s standing rule is "enough to draw it, and
nothing else", and nothing draws the role. The role is what you would *edit*,
and editing is the drawer's job, not the board's.

## 5. What must not go out

`_shape`'s docstring already refuses to broadcast prompts. The same reasoning
covers the binding, and harder: a `ProviderSpec` holds `base_url` and
`api_key_env`. Neither is a secret by itself, and neither has any business on a
board.

**Only `ResolvedModel.model` crosses the wire — the bare id, never the
provider, never the endpoint.** A test asserts the payload contains no
`base_url` and no `api_key_env`, so this cannot rot into a leak by someone
later serving the whole `ResolvedModel` because it was convenient.

## 6. A role the binding never heard of

`resolve()` falls back to `default` for *any* role, which #112 spelled out:
`role: classifer` does not fail, it silently gets the default model. That fix
made the daemon warn at load. This makes it **visible**, which is better,
because the board draws what will actually run rather than what the file asked
for — two nodes that were meant to differ show the same model id, side by side,
and the typo is in the picture instead of in a log line somebody has to still
be watching.

So the board does not mark an undeclared role, and does not need to. It shows
the truth; the daemon's warning names the cause. Adding a badge would be a
second, weaker telling of the same thing.

`BindingError` survives only for a binding with no default to fall back on.
There, `/api/flows` follows the rule `_review_state` already set — *a thing we
cannot read is not a reason to fail the whole listing* — and serves `null`,
which draws as a node with no model line. A board that cannot say what runs a
node is worth more than a board that will not paint.

## 7. Tests

Test-first, as the plans here are:

**Server**
- a node on a role resolves to that role's model id
- a node with no `role` resolves through the graph's `default_role`
- a router's `model` is `null`
- one graph served by two flows on different bindings reports different models
- the `/api/flows` payload contains no `base_url` and no `api_key_env`
- a role the binding never declares reports the default's model — the one
  that will really run, not the one the node asked for
- a binding with no default at all serves `null` and a 200, not a 500

**Skin**
- every node resolving alike puts one model on the header line, shut and open
- two distinct models put a count on the header and the id on each node
- a router pill carries no model

## Out of scope

- **Editing the binding from the board.** This shows; it does not rebind.
  Roadmap item 6's remaining slice owns editing.
- **Provider disambiguation.** Two providers serving the same model id would
  draw the same string twice. Real, rare, and a `provider:model` string is
  worse for everyone else; revisit when someone actually hits it.
- **Token and cost figures on the board.** Every run records spend, and the
  drawer is where a number that changes every few seconds belongs.
- **Per-node `params`.** `temperature: 0` on one node is a real difference and
  is not drawn. The model id answers "what is this costing me"; params do not.
- **`atelier`.** It is a metaphor, not a diagram. A model id on a forge would
  be a label on a painting.
