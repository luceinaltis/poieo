# Architecture

poieo runs LLM workflows on the user's own machine, around the clock. Everything
below exists to make one sentence true: *the work the user described keeps
happening, and they can always see and undo what it did.*

## The two-file split

The organising idea, and the invariant every component respects:

```
graph (logical)                     binding (physical)
  a node names a ROLE      ──────►    a role names a provider + model + params
  "classifier", "writer"              ollama:llama3.2:3b, claude:claude-opus-5
```

A graph never names a model; a binding never names a step. Moving a workflow
from a laptop model to a frontier one is a `--binding` flag, not an edit. Anything that
would make a graph mention a model — or a binding mention a node — is wrong,
however convenient.

## The layers

```
       cli.py  ·  web/server.py            entry points: two front ends, one library
            │
   ┌────────┴──────────┐
   │                   │
 card.py           daemon/config.py         what to run
   │  expands into       │  reads tasks
   └────────┬────────────┘
            │
      graph.py + binding.py                 the two-file split, validated at load
            │
      runtime/executor.py                   the walker: one node, then the next
            │
      runtime/nodes.py                      agent · router · command · confirm
            │            ╲
   providers/            tools/             who answers          what it may touch
            │
      store.py · workspace.py · memory/    what it left behind
```

Nothing points upward. `runtime/` knows nothing about the daemon, `tools/`
knows nothing about containers (`tools/docker.py` does), `workspace.py` is the
only module that knows git exists.

## One run, end to end

A trigger fires (or `poieo run` is typed). Then:

1. **Payload.** The task's static `input:`, plus `input_file:` if named, plus —
   for a task card — its journal and the project's memory. Re-read every run, so
   a note left at 8am is in effect at 9am. → [tasks.md](tasks.md), [memory.md](memory.md)
2. **A place to work.** If the task names a `workdir`, the runner opens a private
   copy of it — a git worktree on a branch of its own. The user's own checkout is
   never written to. → [workspace.md](workspace.md)
3. **Preflight.** Every role the graph needs resolves against the binding; every
   agent node has somewhere to work. Failing here costs nothing; failing later
   costs tokens. → [runtime.md](runtime.md)
4. **The walk.** `execute()` starts at `graph.entry` and loops: run the node, take
   the `next` it returns, repeat until `None`. Cycles are allowed and `max_steps`
   bounds them. → [runtime.md](runtime.md)
5. **Each node.** An `agent` node renders its prompt and calls the model bound
   to its role; if it was given `tools:`, it loops until the model answers
   without calling one. A `router` evaluates conditions and picks a successor,
   calling no model at all.
   → [runtime.md](runtime.md), [tools.md](tools.md)
6. **The record.** Every step appends a JSON line to `runs/events/<run_id>.jsonl`;
   the run's summary lands in `runs/index.jsonl` and its full outputs in
   `runs/results/`. → [storage.md](storage.md)
7. **The change.** Whatever the run wrote in its private copy is committed as one
   change, with the model's own closing sentence as the subject. In the morning
   the user reads it as a diff and accepts or discards it.
   → [workspace.md](workspace.md)
8. **The journal.** A card appends one line to its journal — what it did, or why
   it failed — which is what the next run reads first. → [tasks.md](tasks.md)
9. **The handoff.** If the task's `then:` block has a branch that matches what
   the run left behind, the task it names wakes and reads this run as
   `input.sender`. → [daemon.md](daemon.md)

## Invariants

These are load-bearing. A change that breaks one is a design change, not a fix.

**Fail at launch, not at 3am.** Every graph, binding, expression, cron
expression, memory entry, credential and container image is checked when the
config loads. `load_tasks()` is where this is enforced for the daemon; the
`Spec`/`Binding`/`Expression` errors it raises all mean *misconfigured*, not
*flaky*.

**An in-run failure never kills the daemon.** `execute()` does not raise for a
failure inside a run — the error lands on `RunResult.error`, classified into a
user-facing `Cause`, and the next trigger starts fresh. Only spec and binding
problems raise. A task that fails the same way three times in a row pauses
itself rather than failing all night.

**One source of truth for each thing, and no second copy.** Graphs, bindings,
cards and journals are YAML and markdown under git. The long memory is the one
exception and it is the same rule: `memory/longterm.sqlite3` is the memory,
not a cache of it, so a change to its shape migrates rather than rebuilds.
`memory/cache/` is derived and safe to delete at any moment.

**Everything unbounded has a ceiling.** `max_steps` for a graph, `max_turns` for
an agent node, a timeout for a command, `MAX_CHAIN` for a chain of handoffs,
`max_iterations` for a trigger. Endless wandering becomes a recorded failure and
the next trigger starts fresh.

**Hide the mechanism, never the result.** The user's vocabulary is three words —
a *task*, a *run*, a *change*. Worktrees, containers, refs and indexes are
machinery and stay out of the interface. The one exception is the moment the
user's own files are about to change, where poieo says exactly what will happen.

**One reading of a run.** What the journal shows, what the run record keeps, and
what the change's commit says are all `task.closing_line(result)` — the last
node on the path that produced text. Three readings would eventually tell three
stories about one night.

## Sugar, and what it expands to

A *task card* is one file: a name, a folder, a prompt. At load time it expands
into a task plus a one-node graph indistinguishable from hand-written ones, so
nothing below the loader knows cards exist. `poieo show` prints the expansion and
`poieo eject` writes it out as a real graph. That visibility is what keeps the
short form from becoming a second, hidden configuration format.

## Where the seams are

Three places are deliberately swappable, and each has exactly one chokepoint:

| seam | chokepoint | today |
|---|---|---|
| which backend answers | `providers.register()` / `ProviderPool.get()` | anthropic, openai_compatible, ollama, mock |
| where tools run | `tools.make_executor()` | local (path-confined), docker |
| what a node type does | `runtime.nodes.NODE_TYPES` | agent, router, command, confirm |

Adding to any of these should be one module and one registry line. If it is
not, the seam has leaked.
