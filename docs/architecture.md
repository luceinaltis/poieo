# Architecture

poieo runs recurring model work on the user's machine. A project describes the
work, the daemon schedules it, the runtime executes it, and the store makes the
result visible to the CLI and the browser. When the work happens in a Git
repository, each task uses a private copy so the user can review, accept, or
discard its changes.

## The central split

A [graph](graph.md) describes logical work. Its agent nodes name roles such as
`writer` or `reviewer`; they never name model endpoints. A [binding](binding.md)
maps those roles to providers, models, and generation parameters; it never names
graph nodes.

This split is a contract. Changing where a workflow runs must not require
editing the workflow, and changing the workflow must not require embedding a
provider choice in it.

## From project to run

1. A [project](storage.md) is found from its nearest `poieo.yaml`. The project
   points to its task folder, default binding, run store, and optional learning
   schedule.
2. A [task card](tasks.md) is validated and expanded to the same task and graph
   forms used by explicit graph files.
3. The [daemon](daemon.md) validates every runnable task, graph, role,
   credential, folder, and requested isolation image before arming triggers.
4. A trigger starts a run. The daemon opens the task's [workspace](workspace.md)
   when Git can provide one and builds the input from the card, journal, memory,
   and any input file.
5. The [runtime](runtime.md) walks the graph. Agent and command nodes reach the
   outside world only through provider and tool interfaces.
6. Events and the final summary go to the [run store](storage.md). The daemon
   records the task journal and run result, commits reviewable work, preserves a
   pending question, and evaluates any `then` handoff.
7. The [web service](web.md) and CLI read the same stores and daemon controls;
   neither implements a second execution path.

## Ownership boundaries

- `card.py` owns the authored short form and its expansion. Runtime code does
  not know that cards exist.
- `graph.py` and `expr.py` own workflow shape and safe expressions.
- `binding.py` and `providers/` own model resolution, credentials, provider
  capability adaptation, usage, and cost.
- `runtime/` owns exactly one run. It knows neither schedules nor task folders.
- `daemon/` owns residency: triggers, live reload, holds, questions, handoffs,
  workspaces, and graceful shutdown.
- `layout.py`, `project.py`, and `store.py` own project discovery and durable run
  history.
- `memory/` owns long-term memory; `card.py` owns each task's journal.
- `tools/` owns filesystem, process, notes, and isolation boundaries.
- `workspace.py` is the only module that knows Git.
- `web/` and `cli.py` are interfaces over these components, not alternate
  implementations of them.

## Failure boundaries

Configuration errors fail before a task is armed or a one-shot run begins. Once
a run has started, expected node and provider failures become a failed
`RunResult`; they do not escape and stop the daemon. Optional memory, journal,
review, and display work may warn and degrade, but must not erase the primary run
record or turn an isolated task into an unisolated one.

Files that are the sole source of truth are migrated forward and never rebuilt
from caches. Derived indexes, model catalogues, containers, and build caches may
be recreated. The distinction is documented by the component that owns each
file.

## Extension seams

The intended seams are small registries and protocols:

- providers register endpoint implementations;
- node types register runtime builders;
- toolsets register model-visible tools;
- executors decide where commands run;
- `RunStore` implementations decide where events and summaries are kept or
  broadcast;
- `Workspace` owns reviewable changes;
- the web skin registry decides how the same stage state is presented.

New behavior should enter through one of these seams instead of teaching every
layer a new special case. It must also keep the product vocabulary to **task**,
**run**, and **change**.
