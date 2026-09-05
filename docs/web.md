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
| `GET /api/runs?project=&task=&limit=` | `{runs}` newest first; project and task filters may be combined |
| `GET /api/runs/{run_id}` | `{run_id, events}` or 404 |
| `GET /api/runs/{run_id}/diff` | `{run_id, change: null}` when there is nothing reviewable, otherwise base/head, files, bounded patch, and truncation flag |
| `GET /api/projects/{project}/models` | live binding catalogue: roles and endpoints with model metadata, usage assignments, credential variable name and set/unset state; never a credential value or full base URL |
| `GET /api/projects/{project}/models/undeclared` | `{undeclared}` engines detected on this machine but absent from the project's binding |
| `GET /api/projects/{project}/memory` | long-term-memory page, upkeep statistics, search capabilities, and a bounded relationship graph; supports `If-None-Match` and 304 |
| `GET /api/projects/{project}/memory/{slug}` | one complete entry with metadata, relationships, second-look reasons, and write history, or 404 |
| `GET /api/projects/{project}/tasks/{task}` | card file and parsed `name`, `folder`, `prompt`, `enabled`, plus whether the simple form can preserve it |
| `GET /api/events?task=` | server-sent stored events and `tasks_changed` notifications |

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
branch. Pause, resume, and run-now change daemon state only. An answer persists
with its run and may start a task handoff.

### Models and cards

| request | body and result |
|---|---|
| `POST /api/projects/{project}/models/use` | `{target: "provider/model", role: "default"}`; edits the project binding and reports whether the running daemon adopted it |
| `POST /api/projects/{project}/models/add` | either `{engine}` from detection or `{url, name?, key_env?}`; declares an answering endpoint but does not select it |
| `POST /api/projects/{project}/tasks` | `{name, folder, prompt, enabled?}`; creates one card and returns its task id and path |
| `PUT /api/projects/{project}/tasks/{task}` | `{text}` or simple `{name, folder, prompt, enabled?}`; atomically validates and replaces one card, returning whether the edit is live |
| `PATCH /api/projects/{project}/tasks/{task}` | `{name}`; renames the card file, and therefore the task id, carrying its journal to the new name |
| `DELETE /api/projects/{project}/tasks/{task}` | moves the whole card under `tasks/.set-aside/` and pauses its resident runner |

Model routes write only the project's default binding and never accept or return
a credential value; `key_env` is a variable name. Rebind validates before
keeping a write and reports separately whether the resident daemon accepted the
new binding.

Browser-created and browser-edited cards are confined to the project's task
folder, and their work folder or explicit graph must stay inside the project.
Names are converted to safe filenames and never overwrite an existing card.
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
dropped rather than blocking a run. `run_started` establishes project/task
identity for later frames; the final summary is sent as a flat `run_summary`.
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

`App.tsx` owns project selection, the memory place, and the single active side
panel: task detail, models, task creation, or closed. It shows one project's
stage at a time and keeps only view preferences in local storage. The task
drawer leads with whether the reader must act and the latest or selected run's
result, time, duration, change, or usage. That run owns its lazily fetched
activity before the full-history picker: each tool call leads with the model's
short purpose, while its exact recorded input and result stay in a closed
disclosure. Older calls without a purpose use a conservative description from
their tool and subject. Full history and `Task setup` remain closed below;
selecting an older run keeps that run in view while live summaries continue.
Shared action handling prevents a double press from issuing two mutations and
keeps refusals visible as results.

Skins are plain-DOM renderers behind `skins/contract.ts`. The registry currently
provides the task board and a standalone runs view; both consume the same stage
state. Memory is a separate project view because it fetches its own graph and
search evidence rather than consuming task events. While open it revalidates
the overview every 15 seconds with an ETag and preserves the current query and
selection across an unchanged response. Only declared memory relationships are
drawn as edges; search scores and answer citations highlight evidence without
inventing topology. Those relationships also form stable three-dimensional
regions: dense memories share a faint nebula, pair-sized islands join their
strongest neighbour, and connected regions settle near one another while
set-aside memory remains in the outer shadow. Region positions come from their
own memory relationships, so an unrelated addition does not rearrange the map.
Each region keeps a reserved screen slot while the place is open, and connected
regions take neighbouring slots. Large graphs skip decorative haze and taper point
size so neighbouring regions remain distinct. Adding a task presentation belongs
in the skin registry and must not add another event reducer or transport path.

Any change under `web-ui/src/` must rebuild and commit
`src/poieo/web/static/` in the same PR. See [contribution.md](contribution.md).
