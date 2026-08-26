# Flow Handoff Design

**Date:** 2026-08-26
**Status:** Approved for planning
**Relates to:** DESIGN.md roadmap item 7 (tasks that work together) — its second
half. Item 7 shipped the half that carries *news*: `2026-08-23-task-notes-design.md`
gave a task the `tell` tool and was careful that **"a note wakes nobody"**. This is
the other half: work that finishes and decides what should happen next.

## Goal

Flows are islands. Every trigger poieo has — `manual`, `interval`, `cron`,
`loop` — answers to a clock or to a person, and none answers to another flow.
So the thing a user reaches for first cannot be said at all:

> When `chores` finishes, review what it did. Unless it broke — then tell me
> instead. Unless it changed nothing — then don't bother either of us.

Today that is three separate crons and hope. What is missing is not a scheduler
feature; it is the sentence *"and then"*.

Note what is **not** missing. Steps that always follow each other are already a
solved problem — that is what `next:` is, inside a graph, with ordering, retries
and branching already working. This design is for the other case: two flows with
**different rhythms** that must occasionally join. `chores` runs at 2am; `review`
should run *when there is something to review*, which is not a time.

## 1. The shape

The branch lives on the flow that finishes, in one block, reusing the router's
words exactly:

```yaml
flows:
  - name: chores
    graph: graphs/agent-task.yaml
    trigger: {type: cron, expression: "0 2 * * *"}
    then:
      - when: "run.status != 'completed'"
        to: alert
        label: broke
      - when: "run.change and run.change.insertions > 200"
        to: deep-review
        label: big
      - when: "run.change"
        to: quick-review
        label: small

  - name: quick-review
    graph: graphs/review.yaml
    trigger: {type: manual}
```

`when` / `to` / `label` are `graph.Branch`, imported, not re-declared. **First
match wins and only one fires**, exactly as a `router` node routes.

**There is no `default`.** A router needs one because a run has to go
*somewhere*; a finished run does not, and handing off to nobody is what most
flows do. So falling off the end of the list means "nothing happens", and a
catch-all is a last branch whose condition is `"true"`. `to: null` still means
*stop here* — the router's own null — which is how a branch says "matched, and
deliberately no further" ahead of later branches.

(A `default:` key beside the list would not even parse: YAML cannot hold a
sequence and a named key at the same level. `NodeSpec` gets away with it because
`branches` and `default` are two fields of the node, not one.)

This is principle 7 doing its job: a user who has read one graph can read this
block without being told anything. No new words enter the vocabulary.

**No new trigger type.** The receiving flow needs no change at all beyond
`trigger: {type: manual}`, whose docstring already reads *"the flow only runs
when something asks it to"*. Something can now ask. An earlier sketch of this
design put `type: after` on the receiver; it was a second way to say what
`manual` already said.

### Why the sender declares it

The alternative — each flow declaring what wakes it — spreads one chain across N
files. Adding a consumer would not touch the producer, which is the only thing it
buys, and the cost is that no single place says what happens after `chores`. A
chain nobody can read in one screen is a chain nobody will trust at 2am.

## 2. What the condition sees

`run` is the finished `RunResult`, which already carries everything worth
branching on. Nothing new is collected:

| | |
|---|---|
| `run.status` | `completed` / `failed` / `aborted` |
| `run.error`, `run.cause` | the failure, raw and classified (`{slug, said, fix}`) |
| `run.change` | `{files, insertions, deletions, message}`; absent when nothing changed |
| `run.outputs` | what each node produced |
| `run.state` | the scope as the run left it |
| `run.path` | the nodes it actually walked |
| `run.steps`, `run.iteration` | |

`run.outputs` is the interesting one — it lets a flow branch on a judgement its
own graph already made, rather than re-deriving it:

```yaml
when: "run.outputs.category == 'bug'"
when: "'gave_up' in run.path"
```

The condition is `expr.compile_expr` — the same sandbox as router conditions and
prompt templates, with the same whitelist. Nothing is added to it.

**No model runs here.** The branch is arithmetic over a finished run: it costs
nothing, cannot vary between two identical runs, and adds no latency to the
handoff. The judgement it reads may well be a model's — that is what
`run.outputs` is — but the model made it inside the graph, where it is recorded
and reviewable, and this only reads the answer. Syntax is checked at load, by
`Branch`'s own validator; a name that isn't there is caught at evaluation, where
the sandbox already answers *"no 'change' here; this has: …"*.

Note `run.change` is **absent**, not null, when a run altered nothing —
`RunResult.summary()` is deliberate about that. So a branch that reaches into it
guards first: `run.change and run.change.insertions > 200`. `and` short-circuits
in this evaluator, so the guard is enough.

**A condition that raises does not fail anything.** A router that cannot evaluate
a branch raises `NodeError` and takes the run down with it, which is right — the
run is still going. A handoff has no such run: the sender already finished and
landed its change. So the error is logged against the sender, that branch is
treated as unmatched, and the remaining branches are tried. A `then:` block that
cannot decide hands off to nobody rather than pretending.

## 3. What the next run receives

Waking a flow without telling it why is half a feature: `quick-review` has to
know *what* to review.

The upstream result arrives in the downstream run's input under one key,
`from`. `LoadedFlow.read_input` merges it last, beside `input:`, `input_file:`
and the task payload it already merges. The receiving graph reads it with the
templating it already has:

```yaml
prompt: |
  Review what chores just did.
  It said: {{ input.from.change.message }}
  Files: {{ input.from.change.files }}
```

**`input:` is not templated and does not become templated here.** It is a plain
mapping today (`read_input` returns `dict(self.spec.input)` and nothing else),
and prompts are where poieo expands things. Adding a second expansion site so
`input:` could say `{{ from.… }}` would buy nothing the prompt cannot already do.

`from` carries the same object the condition saw, minus `usage`, which is
machinery. One rule, no second list to keep in sync: **whatever the branch could
test, the next run can read.**

*Cost, stated plainly:* `input` is echoed into the `run_started` event, so a fat
`outputs` is written to the run's JSONL on every handoff. Acceptable for the
first slice — the author chose to wire these flows together — but if it bites,
the fix is a `carry:` allowlist, not a silent truncation.

## 4. Firing it

`FlowRunner` already has the machinery. `run_now()` (from flow control) is a
kick that skips the schedule; a handoff is the same kick carrying a payload.
The trigger's grid does not move and its iteration count does not advance,
exactly as run-now promises.

**One handoff waits; the rest are dropped, loudly.** `run_now()` refuses
mid-run today, because iterations never overlap. A handoff instead parks —
but only one, and **the newest wins**. This is the interval trigger's rule
(*"a run that overruns its period skips the missed ticks rather than queuing
them up"*) applied one level up: a review that fell behind should look at the
latest work, not grind through a backlog it can never clear. Every drop gets a
log line naming what was lost. Silent loss is the one outcome this must not
have.

**A paused or self-paused target does not run.** The handoff is dropped with a
log line. That is what paused means, and a handoff is not a reason to override
a human's hold.

### The run must say what fired it

`execute()` is handed `trigger=self.trigger.describe` today, so a run records
its flow's *configured* trigger no matter what actually fired it — a run-now on
a cron flow records `cron 0 2 * * *`. That is already a small lie and a handoff
makes it a real one: nothing in the record would say the run happened because
`chores` finished.

`execute()` takes `fire.reason` instead. A handed-off run records
`after chores (small)`, a run-now records `run now`, and a scheduled run records
what it records now. This is principle 6 — you can always see what it did — and
it is also the only thing the board will need in order to draw the chain.

## 5. Cycles, and not spinning

`then:` can point backwards. `review → fix → review` is a legitimate loop, and
`A → B → A` with a `loop` trigger at the top is a machine that never stops.
Graphs have exactly this problem and solved it with `max_steps`; this borrows
the solution rather than inventing one.

**A handoff carries a depth.** A run fired by a handoff at depth *n* fires its
own at *n+1*; past `max_chain` (daemon-level, default 10) the handoff is refused
and logged. A scheduled run always starts at depth 0, so the guard bounds one
*chain*, not a flow's lifetime.

At load (principle 5 — fail at launch, not at 3am):

- `to:` must name a flow that exists and is loaded; a typo is a startup error,
  as an unknown node id is inside a graph
- `to:` may not name the sender. The postbox already refuses this for notes
  (*"a task does not leave notes for itself"*) and for the same reason: what you
  want is your own next run, which is `loop` or `carry_state`
- every `when:` compiles
- a cycle is **warned about, not refused** — naming the loop it found. Feedback
  loops are legitimate; the depth counter is what makes them safe
- a `then:` on a `loop`-triggered flow is warned about: everything downstream
  inherits that rhythm

## 6. What the board gets

`/api/flows` grows a `then` field per row — the wiring, as authored. That is
all this slice owes the frontend, and it is enough for a view to draw
`chores ─small→ quick-review` later. Run summaries already carry `trigger`,
which §4 makes truthful, so a run can be traced back to the run that caused it
without a new field.

## Out of scope

- **The view.** Once flows point at each other the board is drawing a graph, and
  a card grid is the wrong shape for it. That is its own design —
  `2026-08-27-work-graph-view-design.md` — and it wants this data to exist first.
- **Fan-out** — `to:` takes one name. Two flows from one branch is roadmap item
  9 ("fan-out steps") and touches how runs are counted and reviewed. A chain
  gets the same reach today: what `B` should trigger belongs in `B`'s `then:`.
- **A queue.** One waiting handoff, newest wins (§4). Real backlogs need a
  durable queue with its own review surface; that is a different feature and
  should not arrive by accident.
- **Handing off across projects or machines.** `to:` names a flow in this
  daemon's config.
- **Surviving a restart.** A waiting handoff lives in the resident process, like
  a pause. The durable statement of intent is the `then:` block in the file.
- **`poieo run` (ad-hoc).** Handoffs belong to the daemon; an ad-hoc run has no
  runners to hand to.

## Build order

Three PRs, in this order, each green on its own:

1. **The block and its checks** — `then:` on `FlowSpec` reusing `Branch`; load-time
   validation and warnings (§5). No runtime behaviour: a wired config loads,
   validates, and does nothing yet.
2. **The handoff** — evaluate on run end, park the kick, merge `from` into the
   next payload, depth counter, `fire.reason` into the run record (§2–§5).
3. **The wire** — `then` on `/api/flows` (§6).
