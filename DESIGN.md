# poieo Design

> This document records what poieo promises its user. The current implementation
> of each component lives in `docs/`; `docs/README.md` is the index.

## One line

**Write down the work you want done, and the models you choose keep doing it on
your machine until you tell them to stop.**

The user designs the work. Models perform the hands-on steps. poieo keeps each
task running and records every run. File changes wait for review by default;
the user can authorize a task to apply its verified changes automatically.

The aim is better accuracy for the cost by combining small and large models:
use economical models for routine steps, spend more capability on demanding
steps, and check the result. Today the user chooses the model for each role;
poieo does not automatically optimize those choices. Results and savings must
be evaluated on the user's actual tasks.

## Principles

### Separate the work from the model

A graph describes what happens and names roles such as `writer` or `critic`. A
binding maps those roles to providers, models and generation settings. Moving a
task from a laptop model to a cloud model changes the binding, not the graph.

### Keep the common case small

An ordinary task needs a name and a prompt, and can be asked for in one
sentence to the project's model. It works in the whole project and receives a
schedule, a model role, tools and turn limits from defaults. Narrowing the
folder, schedules, isolation, handoffs and custom graphs remain available when
the work needs them; they are not setup steps for everyone else.

The folder is the project the user opened, never anywhere else, and a task can
be narrowed to a folder inside it. Because that is where the model may edit,
the moment before saving says whose files will change and whether that can be
undone.

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
change that the user accepts or discards. A task can also apply changes under
an explicit permission: allowed files or folders and verification commands.
Changes are checked against the latest project together, then applied one at a
time. Compatible conflicts or failed checks receive one bounded repair and fresh
checks. Unresolved or incompatible work pauses the affected task and preserves
its history.

### Use three product words

The user learns a **task**, a **run** and a **change**:

- A task is the work that keeps running.
- A run is one pass through that task.
- A change is what a run did to files, with its review or application recorded.

Worktrees, providers, indexes and scheduler internals are implementation terms.
They belong in developer documentation, not in the product, except where naming
a mechanism is necessary to explain what will happen to the user's files.

## The experience today

`poieo init` creates a project and records the model endpoints it can reach. A
task card can be written as a name and a prompt, tried once with `poieo run`,
and kept alive with `poieo daemon`. The daemon serves one board for one or more
projects.

From the board a user can:

- create a basic task, edit its name, folder, prompt and one-line schedule,
  and switch it on or off;
- describe the work in a conversation with the project's model and put the
  card it proposes on the form, to check and save -- or, for work in stages,
  make the connected cards it proposes together;
- rename a task or set it aside without destroying its file;
- connect a task to the next one it starts when it finishes -- whenever, on
  success, on failure, or when its answer says a word;
- see task state, graph wiring, model assignments and run history, including
  whether a task applies its own checked changes and what its checks said,
  and watch a run act as it acts: what the model says each turn and each
  tool it reaches for, with the reason it gave, and tell it something while
  it works, which it hears at its next model turn;
- pause, resume or run a task now, and answer a decision it stopped to ask;
- inspect, accept or discard a run's change;
- inspect available models, declare an answering endpoint and choose which model
  serves a role;
- talk with the project in conversations kept with it and there to return to:
  a conversation is a task and each message one of its runs, so what the model
  does while it answers is watched as any run is, and a change it makes is a
  change like any other -- or, while a task runs, speak to that run from the
  same panel and watch it act.

Advanced task fields beyond a one-line schedule, and the wiring of steps inside a task, remain
file-based: a task of several steps and conditions is drawn in the standalone
graph editor, which operates on the same graph schema as the viewer, until the
board hosts that canvas.

## Safety boundaries

- **Space.** File tools resolve paths inside the task folder. Shell commands are
  only pinned to that folder unless the task opts into container isolation.
  Isolation never silently falls back to the host.
- **Recovery.** A Git-backed task works in a private copy. A folder that cannot
  be protected still runs in place, but poieo says that its edits have no built-in
  review or undo. Automatic application requires a private copy and never falls
  back to editing the original folder when that copy cannot be prepared.
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
