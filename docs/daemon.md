# Daemon

`src/poieo/daemon/`

The daemon keeps project tasks resident, fires them on schedule, and exposes
their current controls and events. It owns everything that spans runs:
preflight, triggers, pause state, live configuration checks, private workspaces,
pending questions, handoffs, spend limits, learning passes, and shutdown.

## Runnable configuration

A `TaskSpec` contains:

| field | contract |
|---|---|
| `name` | identity within one project |
| `graph` | graph file, or the task card that expands to one |
| `binding` | optional override of the project's binding |
| `trigger` | manual, interval, cron, or loop |
| `enabled` | persisted off switch |
| `workdir` | default folder for nodes and reviewable changes |
| `input` | static input mapping |
| `input_file` | mapping reread before every run |
| `carry_state` | carry ending graph state into the next run |
| `isolation` | requested command environment |
| `on_error` | continue scheduling or stop after a failure |
| `then` | first-match handoff branches |

Task cards produce this same shape; see [tasks.md](tasks.md). Paths are resolved
relative to the file that owns them.

Before any trigger is armed, loading validates every task, graph, binding, role,
credential variable, work directory, handoff target, memory database, and
requested isolation image. A configuration that cannot run fails as a unit
instead of leaving only some scheduled work alive. Disabled tasks remain
listable but do not require live credentials or an installed isolation image.

A daemon may load several projects. Project display names must be unique, while
task identity is the pair `(project, task)`.

## Triggers

`TriggerSpec` supports:

- `manual` — fires only through run-now or a handoff;
- `interval` — `every`, optional `jitter`, and `run_at_start`;
- `cron` — a local-time `expression`;
- `loop` — starts again after completion, with optional `cooldown`.

All types may set `max_iterations`. A trigger yields one firing and resumes only
after its run finishes, so a task never overlaps itself. Interval timing stays
anchored to its original grid; ticks consumed by a slow run are skipped, not
queued. Loop is sequential rather than a zero-delay event queue.

## One firing

For each firing the runner:

1. rechecks the spend window and current hold state;
2. rereads the task's graph and binding, and validates the new pair;
3. rereads `input_file`, the task journal, and project memory;
4. prepares a private Git workspace when available;
5. executes one run through the shared runtime and store;
6. commits one reviewable change, or records why review could not be prepared;
7. writes the run result and task journal;
8. parks a question or evaluates the first matching `then` branch.

A valid graph or binding edit is adopted at the next run. An invalid edit logs
a warning and the task keeps its last known-good pair; a transient half-written
file must not kill residency. Inputs and memory are always reread and are not
cached across runs.

When the work directory is inside Git, the task runs in its private worktree.
Outside Git it runs in the named folder with a warning: there is no reviewable
copy to accept or discard. See [workspace.md](workspace.md).

## Holds, disabled tasks, and live task files

Pause is runtime state. It takes effect between runs, skips scheduled firings,
and may be cleared by resume. Run-now is an explicit kick but refuses an
in-flight or disabled task. A handoff is dropped for a paused or disabled target;
when the target is busy, one handoff is parked and a newer one replaces it. A
task never accumulates a queue of missed scheduled work.

`enabled: false` is the persisted hard off switch. The task-folder scanner can
apply an edit that changes **only** `enabled` immediately when no run is in
flight. If the same save changes any other task field, the daemon does not adopt
only the convenient part: it marks the task stale and requires a restart. New
simple cards can become resident from the scan; changes that alter startup-wide
resources, such as a missing isolation keeper or the notes roster, also require
a restart. The board exposes the stale reason.

Repeated identical failures pause a task after the safety threshold
instead of spending indefinitely. A successful run or a run waiting on a
question clears the consecutive-failure sequence. Resume clears it as well.

## Questions and handoffs

A confirm node produces `{node, question, choices}` and status `asking`. The
daemon writes the pending run under `runs/asking/`, so a restart does not lose
the decision. The board and `poieo answer` can submit one of the fixed choices.
Answering completes the same run, appends its completed outcome to the journal,
replaces its result record, appends a revised run summary, removes the pending
file, and only then evaluates handoffs. A newer question for the same task
replaces an older one.

Task-level `then` branches evaluate the completed run scope, including outputs,
aliases, status, usage and cost, change, and answer. First match wins. A handoff
stays inside the sender's project, never starts a disabled or paused target, and
keeps at most one pending kick per busy target; the newest replaces the older.
A chain-depth guard bounds feedback cycles.

## Spend, learning, and shutdown

Project `spend` limits sum known stored cost over their configured rolling
window before a task fires. Unknown provider cost is not invented, so the guard
may undercount endpoints without reported cost or configured prices. A refused
fire remains refused until cost ages out of the window; it does not terminate
the daemon.

When `learn` is configured and the project's long-term memory is enabled, a
learning pass may run at its interval only while no armed task is busy. Its
failure is logged and never stops scheduled work. See [memory.md](memory.md).

Shutdown stops accepting new firings, signals active work cooperatively, closes
providers and containers, and closes the web service. Blocking file and Git
operations use worker threads, while container subprocesses are awaited
asynchronously, so one slow operation does not freeze every task or event
subscriber.

## Extension seams

New schedule behavior belongs in a `Trigger`; run behavior belongs in the
runtime; task-file sugar belongs in card expansion. Runner controls should
remain synchronous state transitions exposed identically to CLI and web. Any
new resident resource must be validated before triggers are armed and released
during shutdown.
