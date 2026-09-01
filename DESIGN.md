# poieo Design

> This document records what poieo promises its user. The current implementation
> of each component lives in `docs/`; `docs/README.md` is the index.

## One line

**Write down the work you want done, and the models you choose keep doing it on
your machine until you tell them to stop.**

The user designs the work. Models perform the hands-on steps. poieo keeps each
task running, records every run, and brings file changes back for review.

## Principles

### Separate the work from the model

A graph describes what happens and names roles such as `writer` or `critic`. A
binding maps those roles to providers, models and generation settings. Moving a
task from a laptop model to a cloud model changes the binding, not the graph.

### Keep the common case small

An ordinary task needs a name, a folder and a prompt. It receives a schedule, a
model role, tools and turn limits from defaults. Schedules, isolation, handoffs
and custom graphs remain available when the work needs them; they are not setup
steps for everyone else.

The folder is never inferred. It is the place the model may edit, so the user
must choose it explicitly.

### Prefer local models, allow any chosen model

Local inference is the default fit for work that runs unattended and often.
Cloud APIs and coding-agent subscriptions use the same binding mechanism, but
none is required to create or exercise a project.

### Keep one inspectable source of truth

Project configuration, tasks, graphs, bindings, journals and run logs are plain
YAML, Markdown and JSONL files. Long-term memory is the one durable SQLite file
inside the project; it includes its own change history and is inspected through
`poieo memory`. Derived indexes, build outputs and runtime emphasis live under
`memory/cache/` and may be rebuilt or deleted.

The CLI and browser call the same library operations. An action taken in one
surface must be visible in the other without a second representation to sync.

### Fail before unattended work starts

Graphs, bindings, expressions, schedules, credentials and requested container
images are checked when a task loads. A configuration mistake must not wait for
the next overnight trigger to announce itself.

Failures during a run are different: they are recorded and returned as a run
result, and they do not take down the daemon. Repeated identical failures pause
the affected task instead of producing the same error all night.

### Make every run visible and every file change reversible

Run records show which model answered, which path the graph took, which tools it
called, what it used and what it cost when the provider or binding can say. A
task working in a Git repository uses a private copy. Its edits become one
change that the user accepts or discards; accepting is the only moment poieo
writes those edits into the user's checkout.

### Use three product words

The user learns a **task**, a **run** and a **change**:

- A task is the work that keeps running.
- A run is one pass through that task.
- A change is what a run did to files and left for review.

Worktrees, providers, indexes and scheduler internals are implementation terms.
They belong in developer documentation, not in the product, except where naming
a mechanism is necessary to explain what will happen to the user's files.

## The experience today

`poieo init` creates a project and records the model endpoints it can reach. A
task card can be written as three fields, tried once with `poieo run`, and kept
alive with `poieo daemon`. The daemon serves one board for one or more projects.

From the board a user can:

- create a basic task, edit its name, folder and prompt, and switch it on or off;
- rename a task or set it aside without destroying its file;
- see task state, graph wiring, model assignments and run history;
- pause, resume or run a task now, and answer a decision it stopped to ask;
- inspect, accept or discard a run's change;
- inspect available models, declare an answering endpoint and choose which model
  serves a role.

Advanced task fields and graph wiring remain file-based. The standalone graph
viewer and editor operate on the same graph schema.

## Safety boundaries

- **Space.** File tools resolve paths inside the task folder. Shell commands are
  only pinned to that folder unless the task opts into container isolation.
  Isolation never silently falls back to the host.
- **Recovery.** A Git-backed task works in a private copy. A folder that cannot
  be protected still runs in place, but poieo says that its edits have no built-in
  review or undo.
- **Time.** Graph steps, model turns, commands, handoff chains and triggers all
  have explicit ceilings. A deadline can additionally bound a model step by
  elapsed time.
- **Cost.** Token usage is always recorded when reported. A project may set a
  rolling spend limit when responses report cost or the binding declares prices.
- **Network.** The board listens on loopback by default and has no account system.
  Binding it elsewhere is an explicit choice and emits a warning. Browser writes
  additionally require the board's own origin and host.

## Non-goals

- **Not a multi-user service.** There are no accounts, permissions or team
  workspaces.
- **Not a general-purpose agent framework.** New node types and tools must serve
  the experience of work that keeps running and remains reviewable.
- **No silent discovery at run time.** Detection helps create or extend a
  binding; a run uses the files the project owns.
- **No OS-level sandbox by default.** Path confinement is the zero-setup default;
  stronger isolation is explicit because it requires an image and a container
  runtime.

## Next

- Let the board edit advanced task fields and host the graph canvas that is
  currently standalone.
- Consider fan-out steps, run-log retention and additional isolation backends
  only where they preserve the same task, run and change model.
