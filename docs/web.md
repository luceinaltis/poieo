# Web API and board

`src/poieo/web/`, `web-ui/`

The daemon serves the board at `http://127.0.0.1:8484` by default. `--port`
changes the port, `--no-web` disables it, and `--host` may expose it beyond the
machine with the security trade-off below. The built Vite application lives in
`src/poieo/web/static/` and is checked in so users do not need a JavaScript
toolchain.

## Read API

Project and task together identify a resident task. Project path parameters use
the project's display name; task parameters use the card filename stem.

| request | response |
|---|---|
| `GET /api/tasks` | `{projects, tasks}`; projects include `name`, `root`, and `keeps_copies`; tasks include identity, graph, trigger, status, hold, enabled/stale state, current and last run, review state, pending question, handoffs, and graph shape |
| `GET /api/runs?project=&task=&limit=` | `{runs}` newest first; project and task filters may be combined; `limit` defaults to 20, is clamped from 1 to 50, and is 400 when not a number |
| `GET /api/runs/{run_id}` | `{run_id, summary, events}` or 404; `summary` is the index row, null while the run is in flight |
| `GET /api/runs/{run_id}/diff` | `{run_id, change: null}` when there is nothing reviewable, otherwise base/head, files, bounded patch, and truncation flag |
| `GET /api/runs/{run_id}/memory` | `{run_id, task, shown, prompt}` from the run's record; `prompt` says what the prompt was made of, each part's characters beside its budget (`page`, `memory`, `journal`), or null for a record written before runs measured this; `shown` lists each memory entry the run was shown with `used` (true, false, or null for an entry the memory no longer holds) and its `preview` (the entry's opening words, null for the same), and is null when the record says nothing about memory; 404 for a run nobody recorded |
| `GET /api/projects/{project}/models` | live binding catalogue: roles and endpoints with model metadata, usage assignments, credential variable name and set/unset state; never a credential value or full base URL |
| `GET /api/projects/{project}/models/undeclared` | `{undeclared}` engines detected on this machine but absent from the project's binding |
| `GET /api/projects/{project}/memory` | long-term-memory page as a run sees it and as written, the last learning pass's page suggestion, upkeep statistics (second looks as `{slug, reason}`), search capabilities, a bounded relationship graph, `learning`, the last few learning passes newest first, and `learner`, the size of the learner's next question with the model and window it will face (null window when the binding names none); supports `If-None-Match` and 304 |
| `GET /api/projects/{project}/memory/{slug}` | one complete entry with metadata, relationships, second-look reasons, write history, and `sources`, each source run id with the task its record names (null when the record is gone), or 404 |
| `GET /api/projects/{project}/tasks/{task}` | card file and parsed `name`, `folder`, `prompt`, `enabled`, plus whether the simple form can preserve it |
| `GET /api/projects/{project}/tasks/{task}/memory` | `{task, block}`: what the task will be shown on its next run, read without leaving a trace |
| `GET /api/events?project=&task=` | server-sent stored events and `tasks_changed` notifications; project and task filters may be combined, and `tasks_changed` reaches every reader |

Each task's graph shape includes node IDs, types, connections, model IDs and
tools. An authored node `description` is included when non-empty; prompts and
system messages are omitted. Clients fall back to node IDs when descriptions
are absent, including responses from older daemons.

Model metadata is whatever the endpoint reports. Unknown context, size,
quantization, capability, or price remains null. The undeclared-engine probe is
a separate request so a closed candidate port does not delay the main catalogue.

## Memory API

Memory search uses POST because the query belongs in a JSON body, but it does
not change source memory:

| request | body and response |
|---|---|
| `POST /api/projects/{project}/memory/search` | `{query, mode: "words" | "meaning", limit?, include_set_aside?}`; returns ranked entry previews and the embedding model when used |
| `POST /api/projects/{project}/memory/ask` | `{question, include_set_aside?}`; returns a cited answer, ranked evidence, model usage, and any word-only degradation notice |

A person's four memory writes call the same doors as the terminal's `keep`,
`set-aside`, and `page`. Each is refused with 409 while the project keeps no
memory, and only what a person may say travels: never a source or a seal.

| request | body and result |
|---|---|
| `PUT /api/projects/{project}/memory/page` | `{text}`; replaces the page as written |
| `POST /api/projects/{project}/memory/suggestion` | `{accept}`; lands the last learning pass's page line or lets it go by rewriting the page unchanged; 409 when nothing is suggested |
| `PUT /api/projects/{project}/memory/{slug}` | `{body, scope?, anchors?, links?}`; keeps an entry, rewriting one that exists; an empty object means the person looked and it still holds; 400 for a bad name or shape, 409 for a connection or anchor that names nothing |
| `POST /api/projects/{project}/memory/{slug}/set-aside` | `{because}`: the replacing entry or a sentence saying why; 404 for an unknown entry, 409 for a name-shaped replacement that does not exist |
| `POST /api/projects/{project}/memory/{slug}/put-back` | no body; the entry stands again; 404 unknown, 409 when it was not set aside |

The fixed names `page`, `suggestion`, `search`, and `ask` are routed before the
entry slug, so a PUT to the page cannot be read as an entry called `page`.

Queries are non-empty strings of at most 2,000 characters; result limits are
clamped from 1 to 50. Meaning search returns 409 unless the binding explicitly
declares a supported `memory_embedder`, and ask returns 409 without an explicit
`memory_searcher`. Provider failure is 503. A meaning request may populate the
disposable embedding cache and either POST may spend a model call, but neither
persists the query, answer, or a memory write. Both receive the same origin
check as state-changing requests.

## Write API

All state-changing requests return JSON. Malformed input is normally 400, a
missing project, task, or run is 404, and a valid request refused by current
state is 409.

### Review and control

| request | body and result |
|---|---|
| `POST /api/tasks/{project}/{task}/accept` | optional `{through_run_id}`; fast-forwards or merges reviewable work, or returns dirty/conflict paths |
| `POST /api/tasks/{project}/{task}/discard` | optional `{from_run_id}`; parks and removes that run and later pending changes |
| `POST /api/tasks/{project}/{task}/pause` | no body; returns resulting runtime status |
| `POST /api/tasks/{project}/{task}/resume` | no body; returns resulting runtime status |
| `POST /api/tasks/{project}/{task}/run` | no body; returns `starting`, or 409 with the in-flight run id |
| `POST /api/tasks/{project}/{task}/answer` | `{choice}`; completes the persisted pending question or returns the currently offered choices |

Accept and discard are the only routes that may change the user's checked-out
branch, so a run id given to either must belong to the task in the path; one
recorded under another project or task is 404. Pause, resume, and run-now change
daemon state only. An answer persists with its run and may start a task handoff.

### Models and cards

| request | body and result |
|---|---|
| `POST /api/projects/{project}/models/use` | `{target: "provider/model", role: "default"}`; edits the project binding and reports whether the running daemon adopted it |
| `POST /api/projects/{project}/models/add` | either `{engine}` from detection or `{url, name?, key_env?}`; declares an answering endpoint but does not select it |
| `POST /api/projects/{project}/tasks` | `{name, folder, prompt, enabled?}` or `{name, folder, graph, enabled?}` with a graph document; creates one card, optionally its neighboring graph, and returns its task id and path |
| `PUT /api/projects/{project}/tasks/{task}` | `{text}` or simple `{name, folder, prompt, enabled?}`; atomically validates and replaces one card, returning whether the edit is live |
| `PATCH /api/projects/{project}/tasks/{task}` | `{name}`; renames only the card file and therefore the task id |
| `DELETE /api/projects/{project}/tasks/{task}` | moves the whole card under `tasks/.set-aside/` and pauses its resident runner |

Model routes write only the project's default binding and never accept or return
a credential value; `key_env` is a variable name. Rebind validates before
keeping a write and reports separately whether the resident daemon accepted the
new binding.

Browser-created and browser-edited cards are confined to the project's task
folder, and every path they name — work folder, explicit graph, `binding:`,
`input_file:` — must stay inside the project.
Names are converted to safe filenames and never overwrite an existing card.
Step creation uses the existing graph schema and preflight to check node fields,
templates, conditions, connections, and model roles before writing. Every step
uses the explicitly chosen task folder; node-specific `workdir` is refused.
The server derives `<task>.graph.yaml` beside the card. Complete files are
published without replacement, graph first and card last, so the task scan sees
the complete task. A failed card publication removes the new graph. An existing
graph is never overwritten, and no binding or credential is changed. A failure
to clean up an ignored temporary file is logged without undoing publication.

Structured editing is offered only when it can reproduce every field and
comment; otherwise the client edits the raw file. Set-aside and rename place an
immediate hold on the old runner, while the folder scan or next restart
reconciles the resident roster.

## Browser security

There is no account or login. On the default loopback address, reads rely on
browser same-origin readability and intentionally have no CORS permission.
Every non-read request passes one `SameOrigin` middleware check:

1. when an `Origin` header is present, its network location must equal `Host`;
2. while the daemon is loopback-only, `Host` must also identify this machine.

This blocks cross-site form writes and DNS rebinding. `Origin: null` is refused.
A caller with no `Origin`, such as the CLI or `curl`, is treated as a program.
The scheme is not compared so a local TLS terminator can proxy the board, but
the proxy must preserve the browser's `Host`. Rewriting it makes `Origin` and
`Host` disagree, so every browser write is refused with 403.

Binding to a non-loopback host disables the loopback-host half because the
daemon cannot know every legitimate LAN name. The daemon warns: transport
encryption, authentication, and network access control then belong to the
operator. The board cannot be framed (`frame-ancestors 'none'` and
`X-Frame-Options: DENY`). The HTML shell is not cached; content-hashed assets
are immutable.

## Event flow

`BroadcastStore` writes through to the durable store and publishes the same
event dictionary to a bounded queue for each subscriber. A slow subscriber is
dropped rather than blocking a run, and its queue receives a close sentinel so
its SSE response ends instead of waiting on a queue nothing feeds again.
`run_started` establishes project/task identity for later frames; the final
summary is sent as a flat `run_summary`.
`tasks_changed` belongs to no run and tells clients to reread the listing.

`EventSource` reconnects automatically, but events sent while disconnected are
not replayed by SSE. On every connection the client resynchronizes from
`/api/tasks`, the run index, and the event history of currently running tasks.
Live frames arriving during those reads are queued and folded only after older
history, so the stage cannot move backward. Duplicate live/history frames are
ignored by event identity.

## Frontend state and presentation

`api.ts` owns HTTP and EventSource transport. `shell/stageStore.ts` owns initial
listing, recent-run tallies, catch-up, live ordering, and subscriptions.
`state/stage.ts` is the only event interpreter. Its `StageState` keys tasks by
`project/task` and keeps status, holds, enabled/stale state, current node and
turn, recent model text and tool calls, recent runs, reviewability, schedule,
handoffs, and graph shape. Unknown events are ignored so an older bundle keeps
working with a newer daemon.

The page's root type size follows the window's width, 16px up to a laptop's
and 22px from a large desktop's, and the bar, rail, panels and buttons are
sized in em or rem so they follow it. The board's fit magnifies by the same
factor and no further; it still shrinks to fit a wide graph.

`App.tsx` owns project selection, the memory place, and the single active side
panel: task detail, models, task creation, or closed. It shows one project's
stage at a time and keeps only view preferences in local storage. The rail down
the side lists only places, the views that take the whole stage: board, runs,
and memory, with the current one marked. Panels are not places: models opens
from a button beside the project name on the bar, and new task from a button on
the board itself (the empty board offers it in its invitation instead), and
neither moves the rail's mark. The task
drawer leads with whether the reader must act and the latest or selected run's
result, time, duration, change, or usage. That run owns its lazily fetched
activity before the full-history picker: each tool call leads with the model's
short purpose, while its exact recorded input and result stay in a closed
disclosure. Older calls without a purpose use a conservative description from
their tool and subject. Full history and `Task setup` remain closed below;
selecting an older run keeps that run in view while live summaries continue.
Inside the run's own box, one closed line says what it started with from
memory: the count and how many shaped the answer. Opening it lists one row
per entry with its opening words and what became of it, the ones that shaped
the answer first; each opens the memory place on that entry. Shared action
handling prevents a double press from issuing two mutations and keeps refusals
visible as results.

The new-task form starts with name, folder, and prompt. `Write as steps` keeps
the prompt as the first step and adds model instructions, commands, conditions,
or a question for a person. Results can be inserted into later instructions;
conditions choose an earlier answer or command result, a comparison, a value,
and a destination, with a separate fallback. Conditions keep their first-match
order. A question ends the run; task-level handoffs still belong in the card.
New model steps use the ordinary 40-turn limit and include journal and memory
input. Each graph limits a run to 100 steps including repeats.

The form checks empty instructions, unreachable steps, removed results, and
result reads that could occur before their writer. Server validation remains
authoritative. Failed saves retain the whole draft; successful saves clear it.
This form creates new tasks; editing existing graphs remains file-based.

Each task card shows its step connections at reading size. Every step names
where it comes **From** and where it goes **Next**, with **Start** and **End run**
spelled out. These are execution connections, not data inputs or result values.
Conditions keep their order and destinations, even when two choose the same
step. Return paths name the earlier step. Names and conditions wrap within the
card; repeated descriptions include IDs to distinguish their destinations.
Steps appear once in entry-first reading order, with a vertically scrollable
region for long tasks. Scrolling that region does not zoom the board.

**View steps** opens a native dialog outside the board's pan/zoom transform,
with an independent scrollable canvas, zoom controls, fit, and a 100% reading
size. Nodes use authored descriptions, an entry marker, model assignments and
explicit endings. Dagre lays this graph out from left to right, reserves space
for wrapped conditions, and retains a separate edge for each branch.
The router's otherwise path is always drawn, including an omitted default that
ends the run; return paths retain their arrows. Conditional paths are amber.
Running-step updates highlight both views without rebuilding their steps or
resetting their scroll or the chosen zoom. Removing the task closes the dialog, and closing
restores focus to its opener. Narrow screens use the full viewport.

Skins are plain-DOM renderers behind `skins/contract.ts`. The registry currently
provides the task board and a standalone runs view; both consume the same stage
state. Memory is a separate project view because it fetches its own graph and
search evidence rather than consuming task events. While open it revalidates
the overview every 15 seconds with an ETag and preserves the current query and
selection across an unchanged response. Its caption puts two sizes against their
limits with one shared gauge: the page against its character budget, and the
learner's next question against the window the binding declares for the learner,
in tokens estimated from the last pass that counted (four characters a token
before one has); with no window declared the question is shown in characters and
no bar is drawn, since an unknown limit is not a limit of zero. The fill's colour
and a word both say when a value is near or over its limit. The evidence pane is also where a person
writes: the page, a new memory, a set-aside for the selected one, and the last
learning pass's suggestion; a refused write stays visible as a result, and a
successful one rereads the overview at once. Only declared memory relationships are
drawn as edges; search scores and answer citations highlight evidence without
inventing topology. Those relationships also form stable three-dimensional
regions: dense memories share a faint nebula, pair-sized islands join their
strongest neighbour, and connected regions settle near one another while
set-aside memory remains in the outer shadow. Region positions come from their
own memory relationships, so an unrelated addition does not rearrange the map.
Each region keeps a reserved screen slot while the place is open, and connected
regions take neighbouring slots. Large graphs skip decorative haze and taper point
size so neighbouring regions remain distinct. An entry's source runs open the
task drawer on that run while the run's record still exists, and the evidence
pane lists the recent learning passes with what each kept, set aside, or let go
and why. Adding a task presentation belongs in the skin registry and must not
add another event reducer or transport path.

Any change under `web-ui/src/` must rebuild and commit
`src/poieo/web/static/` in the same PR. See [contribution.md](contribution.md).
