# Work Graph View Design

**Date:** 2026-08-27
**Status:** Approved for planning
**Relates to:** `2026-08-26-flow-handoff-design.md`, which gives flows a way to
point at each other. This is the view that draws the result. It needs that data
to exist first: with no `then:` anywhere, this view draws disconnected nodes —
which is exactly what the board is today.

## Goal

The board shows cards side by side. A card is a good shape for *one* flow's
state and a bad shape for the **shape of the work**: three cards in a row cannot
say that one of them feeds another, and they cannot say what steps any of them
takes. The reader is left assembling the picture in their head from the flow
names.

The question this answers is "what does this project actually do, and where is
it right now" — asked once, answered in one screen.

## 1. Everything on screen is a node

There is one visual noun. Some nodes contain other nodes, and those can be
opened.

**Collapsed** — a flow is a node:

```
   ┌──────────┐  changed  ┌──────────┐  approved  ┌─────────┐
   │ ● chores │ ────────> │  review  │ ─────────> │ publish │
   └──────────┘           └──────────┘            └─────────┘
```

**Expanded** — the node opens and its graph's nodes are inside it:

```
   ┌─ chores ──────────────────── daily 2am ─┐
   │  ┌──────┐  ┌─────┐  ┌──────┐  ┌──────┐  │  changed   ┌────────┐
   │  │ scan │─>│ fix │─>│ test │─>│ gate │  │ ─────────> │ review │
   │  └──────┘  └─────┘  └──────┘  └──────┘  │            └────────┘
   └─────────────────────────────────────────┘
```

This is deliberately *not* two levels with a mode switch. A mode makes the
reader remember which one they are in; nesting does not. The vocabulary a reader
has to learn is: **a node, and some nodes open.**

Opening also buys information. Shut, a handoff is an arrow between two borders
and says "when chores finishes". Open, the nodes a run can *stop* on are marked
inside the border, so the same arrow now says which of them it leaves from.

The arrow itself stays border to border rather than anchoring on the node. Its
geometry is then arithmetic over the layout instead of a measurement of the
DOM, which is what lets it be tested at all — and a box that grows when it
opens does not drag its arrows around the screen.

## 2. One rule explains the whole picture

> **An arrow that crosses a border ends one run and starts another.**

| | |
|---|---|
| arrow **inside** a border | same run — the next step, immediately, sharing scope |
| arrow **crossing** a border | **a new run**: a new private copy, and one more thing to accept or discard in the morning |

This is the payoff of drawing both levels the same way. `run` is the hardest
word in poieo to explain in prose — it is one pass through a border, and the
picture says so without a sentence. It also explains, without arguing, why
splitting one job across two flows is not free: every crossing adds a review.

The two branch vocabularies line up because the handoff design reuses
`graph.Branch` — `chores ─changed→ review` and `gate ─approved→ publish` are the
same drawing at two scales.

## 3. What opens by default

**A flow that is running opens itself; the rest stay shut.** Detail is only
wanted where something is happening, and a board of ten flows fully expanded is
sixty nodes, which is not a glance.

Every border toggles by hand and the choice sticks, per flow. There is no
expand-all / collapse-all mode: that is a mode again.

## 4. Depth stops at two, structurally

`llm`, `router` and `agent` are the node types, and **none of them contains a
graph**. So the nesting is exactly `flow (open) → node`, and no deeper. This is
not a rule the view enforces; it is a fact about the graph schema, which is why
it cannot rot.

## 5. It replaces the ledger, and takes the name `basic`

Not a third skin. `web-ui/src/skins/ledger/` becomes `web-ui/src/skins/basic/`,
`id: "ledger"` becomes `id: "basic"`, and the card grid is what the graph
replaces. Reasoning: the ledger's job was always "the plain view of what is
going on", and a graph does that job better; keeping both would be keeping a
worse answer to the same question.

`atelier` is untouched, and stays the default skin.

The rename migrates itself. `skinById` in `registry.ts` already lands an
unknown id on the fallback, and the fallback becomes `basic` — so a reader with
`"ledger"` in `localStorage` opens on the new view with no migration code.

## 6. What it draws from

Everything comes through `StageState`, as the skin contract requires — a skin
never fetches.

- **Structure** — each flow's `then:` wiring, and its graph's `entry` plus each
  node's `next` / `branches` / `default`. Served on `/api/flows`; seeded into
  the stage at `initialStage`, alongside the `tracked` and `lastRun` it already
  seeds.
- **State** — `currentNode`, `status`, `step`, which the reducer already tracks.

The split matters for how it paints: **structure is drawn once and does not
move; only the highlight moves.** `changedWorkers` (reference equality per
flow) already gives skins the "what actually changed" signal, and a graph that
re-laid-out on every SSE frame would be unreadable as well as slow.

Node positions inside a border come from `NodeSpec.ui: {x, y}`, which the canvas
editor already writes and `editor.py` already draws from. Only the arrangement
*between* borders is new.

## 7. Clicking

The existing contract is one callback, `onSelectWorker(flow)`, and the drawer it
opens is unchanged. So:

- the border's **header** selects the flow — same as clicking a card today
- a **separate affordance on the border** opens and shuts it

One click must not mean two things. Inner nodes are not clickable in this
slice; what a node's detail would show is the drawer's question, not the
board's.

## Out of scope

- **Editing.** This draws; it does not rewire. `editor.py` is the canvas that
  edits a graph, and folding it in is roadmap item 6's remaining slice.
- **Inner nodes as click targets.** See above.
- **Automatic layout of the graph inside a border.** `ui: {x, y}` is authored,
  and a graph with no coordinates gets a simple left-to-right walk from `entry`
  rather than a layout engine.
- **The card's remaining machine vocabulary** — `review · llm · step 2`. Real,
  and its own change. (The other half of this bullet, counting runs as
  "pieces of work", has since landed: the board says *run* now, as DESIGN
  principle 7 does.)
- **Very large boards.** Ten flows is the shape being designed for. A hundred
  wants search and filtering, which is a different screen.
