# Storage

`src/poieo/layout.py`, `src/poieo/project.py`, `src/poieo/detect.py`,
`src/poieo/store.py`

A project is the folder containing the nearest `poieo.yaml`. The marker names
shared locations and defaults; task, graph, binding, memory, and run-store
components own the contents at those locations.

## Project marker

```yaml
version: 1
name: night shift
store: runs
spend: {limit: 1.0, over: 1h}
binding: models/default.yaml
tasks: tasks/
learn: 1d
```

All keys have defaults or are optional, and unknown keys are rejected. `name`
falls back to the project folder's name. `store` defaults to
`runs`; `binding` is the default for tasks and one-shot runs; `tasks` names the
card folder; `learn` enables a daemon learning interval only when long-term
memory is also present. `spend` is a rolling ceiling over known stored cost.

Paths expand `~` when possible and otherwise resolve relative to the marker,
not the process working directory. Command-line paths and flags take priority;
project discovery fills only values the caller did not provide. A component
that needs only the project locations loads `ProjectSpec` without parsing every
task; the daemon extends it when it intends to run them.

## Layout

```text
<project>/
  poieo.yaml
  tasks/                         task cards and graphs
  models/                        bindings
  memory/
    shortterm/<task>.md          task journals
    longterm.sqlite3             long-term memory source of truth
    cache/                       derived blobs, strengths, learning log, builds
  runs/                          or the explicit store path
    index.jsonl                  append-only run summaries
    events/<run-id>.jsonl        append-only event streams
    results/<run-id>.json        complete records used by memory
    asking/<task>.json           pending questions
  worktrees/<task>/              private Git working copies
```

An explicit `store` moves the whole `runs/` family and nothing else. Memory and
worktrees remain with the project because they are project state, not run-log
storage. `Layout` is the single source for these paths and does not create them;
the component that writes a file creates its parent.

## Initialization and discovery

`poieo init` writes a marker, detected default binding, mock binding, disabled
sample task, long-term memory database, agent instructions, and ignore rules.
It never overwrites an existing file and validates the resulting project before
returning. `--mock` produces a runnable offline binding when no real endpoint
should be selected.

Initial model detection probes known candidates concurrently and writes only
the endpoints that answer. It records model ids and any context, size, or price
metadata the endpoint reports; missing metadata remains absent. Credential
variable names may be recorded, credential values may not. Detection is not a
background source of truth: `poieo config add` explicitly probes again when a
new endpoint is installed later.

Provider-specific catalogue parsing belongs in detection adapters. Adding a
candidate address must not change binding resolution or make runtime calls probe
the network unexpectedly.

## Run store

Each event is one JSON object appended to
`events/<run-id>.jsonl`. One summary per finished attempt—`completed`, `failed`,
`aborted`, or `asking`—is appended to `index.jsonl`; a later revision of the
same run appends another row. Readers scan newest-first and use the newest row
for a duplicate run id, which preserves append-only recovery while allowing a
pending question to be completed.

Event appends are serialized within the process and rely on the operating
system cache. The summary append is flushed and synchronized once per run,
because it is the durable answer to “what ran?” Readers skip blank, malformed,
or half-written JSONL lines and can still return earlier intact records. Listing
reads backward only until it has enough project/task matches; it does not parse
the entire lifetime of the daemon.

`spent_since` sums the newest revision of runs whose known cost falls inside a
window. Missing cost contributes nothing rather than an estimate. `NullStore`
drops both writes and reads for explicit no-log runs and tests.

The web layer wraps stores rather than changing their contract:
`BroadcastStore` publishes appends to live subscribers, while `MergedStore`
combines several project stores and preserves project identity.

## Durability rules

- Marker, task, graph, binding, journal, long-term memory, and run-history files
  are source data. Do not rebuild or silently replace them from a cache.
- `memory/cache/`, containers, build outputs, and web state are derived and may
  be recreated by their owners.
- A write that can arrive after a crash must be append-only or use a temporary
  file followed by an atomic replace.
- A corrupt optional record may be skipped with a warning; a corrupt project
  configuration or sole-copy memory schema must fail visibly.
- Project and task filters travel together once histories from several projects
  share a board.
