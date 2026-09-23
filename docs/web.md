# Web API and board

Task setup exposes an optional Changes section; a new task starts under review
and the new-task panel does not ask. Review is the default; automatic
application requires explicit selection and verification commands. The setup
form also supports file/folder scope. Card reads expose `apply`
and `keeps_copies`; creation and rewrites validate application settings before
writing. Editing only the prompt preserves an existing permission. Comments
and advanced fields continue to use the file editor. Application-only edits
take effect at the next run. Automatic mode requires Git in the selected task
folder and explains that work stays in a private copy until checks pass.

Run history labels applied, pending and blocked changes and shows each command,
exit code and output on demand. Applied changes do not add to the review count.
An application question immediately marks the affected task paused in the event
stream. Refusals explain scope, stale work and verification-modified files.

Acceptance on a running task goes through the runner's application checks.
Accept/discard refuse while that task is working, and a selected run must belong
to the requested project and task. Refusals also include stale candidates,
changed verification files, out-of-scope files and failed commands; absence of
the expected `accepted`/`discarded` result makes the HTTP response 409.

`POST /api/tasks/{project}/{task}/undo` takes `{run_id}`. Only an applied run
belonging to that task can be undone. It returns the new undo run and application
result; incompatible changes or failed checks return 409 without changing files.

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
| `GET /api/tasks` | `{projects, tasks}`; projects include `name`, `root`, and `keeps_copies`; tasks include identity, `title` (the card's own `name:`, or the task name without a card), graph, trigger, status, hold and why it is held (`held_because`, the daemon's own sentence or null), enabled/stale state, current and last run, review state, pending question, handoffs (`then`, each `{to, label, when}`; `label` falls back to the condition), graph shape, `apply`, the task's permission to apply its own work (`mode`, `paths`, `checks`), `chat`, true for the task the chat speaks to, which the board leaves off its stage, and `permission`, which of the chat's settings its card on disk holds -- `read`, `ask`, `edits`, `all`, or `custom` for a hand-written mix -- and null for every other task |
| `GET /api/runs?project=&task=&limit=` | `{runs}` newest first; project and task filters may be combined; `limit` defaults to 20, is clamped from 1 to 50, and is 400 when not a number |
| `GET /api/runs/{run_id}` | `{run_id, summary, events}` or 404; `summary` is the index row, null while the run is in flight |
| `GET /api/runs/{run_id}/files/{name}` | a file kept with the run: what was attached to the message that started it, or a picture the model looked at (named by `preview` on its tool call); served as the picture its bytes say it is, otherwise as plain text, with `nosniff`, never as a page; 404 for any other name |
| `GET /api/runs/{run_id}/diff` | `{run_id, change: null}` when there is nothing reviewable, otherwise base/head, files, bounded patch, and truncation flag |
| `GET /api/runs/{run_id}/memory` | `{run_id, task, shown, prompt}` from the run's record; `prompt` says what the prompt was made of, each part's characters beside its budget (`page`, `memory`, `journal`), or null for a record written before runs measured this; `shown` lists each memory entry the run was shown with `used` (true, false, or null for an entry the memory no longer holds) and its `preview` (the entry's opening words, null for the same), and is null when the record says nothing about memory; 404 for a run nobody recorded |
| `GET /api/projects/{project}/models` | live binding catalogue: roles and endpoints with model metadata, usage assignments, credential variable name and set/unset state; never a credential value or full base URL |
| `GET /api/projects/{project}/folders` | `{folders}`: the project and the folders under it, two levels down and at most 200, each as `path` (how a card spells it, relative to the tasks folder) and `name` (how a person reads it); hidden and dependency folders, the tasks folder and the project's runs, worktrees and memory are left out |
| `GET /api/projects/{project}/models/undeclared` | `{undeclared}` engines detected on this machine but absent from the project's binding |
| `GET /api/projects/{project}/memory` | long-term-memory page as a run sees it and as written, the last learning pass's page suggestion, upkeep statistics (second looks as `{slug, reason}`), search capabilities, a bounded relationship graph, `learning`, the last few learning passes newest first, and `learner`, the size of the learner's next question with the model and window it will face (null window when the binding names none); supports `If-None-Match` and 304 |
| `GET /api/projects/{project}/memory/{slug}` | one complete entry with metadata, relationships, second-look reasons, write history, and `sources`, each source run id with the task its record names (null when the record is gone), or 404 |
| `GET /api/projects/{project}/tasks/{task}` | card file and parsed `name`, `folder`, `prompt`, `enabled`, `schedule` (the card's `every:` or `at:` as one line, `manual` for a `trigger: {type: manual}` with nothing else in it, or empty), plus whether the simple form can preserve it |
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
| `POST /api/tasks/{project}/{task}/undo` | `{run_id}`; verifies and applies the inverse of an applied change, preserving later work, or returns why it was blocked |
| `POST /api/tasks/{project}/{task}/pause` | no body; returns resulting runtime status |
| `POST /api/tasks/{project}/{task}/resume` | no body; returns resulting runtime status |
| `POST /api/tasks/{project}/{task}/run` | no body, or `{message, thread?}`: what a person says to start the run, at most 4,000 characters, and the conversation it continues, 1 to 64 letters, digits, `-` or `_`; with `attachments`, at most 4 `{name, media_type, data}` in base64 -- PNG, JPEG, GIF or WebP up to 3,750,000 bytes each, told apart by their bytes, or UTF-8 `text/plain`, `text/markdown`, `text/csv` or `application/json` up to 200,000 characters, each under one plain file name; the run reads the message as `input.message`, its first model step is shown the attachments beside its prompt, a picture as one and a text file as its words, and its record keeps the message, the thread and the attachments' names, the files themselves kept under `runs/files/<run-id>/`; returns `starting`, 400 for a body that is not that, or 409 with the in-flight run id |
| `POST /api/tasks/{project}/{task}/approve` | `{call, allow}`: a person's answer to a tool call the run in flight is waiting on (`node_tool_asking` names the call); returns `answered`, 400 for a body that is not that, or 409 when nothing is waiting on that call |
| `POST /api/tasks/{project}/{task}/permission` | `{mode}`, one of `read`, `ask`, `edits` or `all`: what the chat may do, written into the chat card's `tools` and `ask_before` and read by its next run -- `read` looks only; `ask` edits and runs commands, asking before each; `edits` edits unasked and asks before a command; `all` asks about nothing; everything else on the card is kept; returns `{permission}`, 400 for another mode, 409 for a task that is not the chat's or a chat card written by hand -- a JSON card, or one carrying a comment, which a rebuild would break or lose |
| `POST /api/tasks/{project}/{task}/answer` | `{choice}`; completes the persisted pending question or returns the currently offered choices |

Accept and undo can update the checked-out project; discard removes pending
work from the task's private copy. A run id supplied to any review action must
belong to the named task and project. Accept and discard return 404 for a run
recorded elsewhere; undo returns 409 for a run it cannot undo.
Pause, resume, and run-now change
daemon state only. An answer persists with its run and may start a task handoff.

### Models and cards

| request | body and result |
|---|---|
| `POST /api/projects/{project}/models/use` | `{target: "provider/model", role: "default"}`; edits the project binding and reports whether the running daemon adopted it |
| `POST /api/projects/{project}/models/add` | either `{engine}` from detection or `{url, name?, key_env?}`; declares an answering endpoint but does not select it |
| `POST /api/projects/{project}/tasks` | `{name, folder, prompt, enabled?, schedule?}` or `{name, folder, graph, enabled?, schedule?}` with a graph document; `schedule` is one line, an interval or `loop` written as `every:`, five cron fields written as `at:`, or `manual` written as `trigger: {type: manual}`, and 400 when none; an optional `then` is written with the card and checked as the rewrite checks it, except that a target may be a card on disk the scan has not loaded yet; creates one card, optionally its neighboring graph, and returns its task id and path; with `chat: true` it writes the project's chat card instead -- no steps, schedule or `then`, the folder the project's own when none is given, the `read` toolset, and 409 when the project already has one |
| `POST /api/projects/{project}/tasks/draft` | `{messages: [{role: "user" \| "assistant", content}]}`, at most 30 turns of 4,000 characters each, the last one the person's; puts the conversation to the `task_writer` role and returns `{reply, draft, drafts, model, usage}`: the model's prose without its cards, every card it proposed in order as `{name, folder, prompt, schedule, after}` (at most four; `after` is `{task, when, word}` naming an earlier card by its place and one of `always`, `succeeded`, `failed`, `says`, or null, and a card with one is `manual`), and `draft`, the first of them without `after`, or null; writes nothing; 409 without a models file, 503 when the model does not answer |
| `PUT /api/projects/{project}/tasks/{task}` | `{text}`, simple `{name, folder, prompt, enabled?, schedule?}` where an absent `schedule` keeps the card's and an empty one drops it, or `{then}`, the card's whole list of connections, spliced into its own text so comments and other fields are kept (an empty list removes the block; a target outside the project or a condition that does not parse is 400, a card whose text cannot be rewritten that way is 409); atomically validates and replaces one card, returning whether the edit is live. The GET beside it returns `then` with each connection's condition |
| `PATCH /api/projects/{project}/tasks/{task}` | `{name}`; renames only the card file and therefore the task id |
| `DELETE /api/projects/{project}/tasks/{task}` | moves the whole card under `tasks/.set-aside/` and pauses its resident runner |

Model routes write only the project's default binding and never accept or return
a credential value; `key_env` is a variable name. Rebind validates before
keeping a write and reports separately whether the resident daemon accepted the
new binding.

Browser-created and browser-edited cards are confined to the project's task
folder, and every path they name — work folder, explicit graph, `binding:`,
`input_file:` — must stay inside the project.
Both forms list the folders that fence would accept, in the card's own
spelling, as their only folder control, standing on the card's folder -- the
project itself (`..`) for a new one -- and showing a folder the list lacks as
one more choice. The list stops two levels down; its last choice, `another
folder…`, opens the folder written out for one deeper, which the fence still
judges.
Names are converted to safe filenames and never overwrite an existing card.
Step creation uses the existing graph schema and preflight to check node fields,
templates, conditions, connections, and model roles before writing. Every step
uses the explicitly chosen task folder; node-specific `workdir` is refused.
The server derives `<task>.graph.yaml` beside the card. Complete files are
published without replacement, graph first and card last, so the task scan sees
the complete task. A failed card publication removes the new graph. An existing
graph is never overwritten, and no binding or credential is changed. A failure
to clean up an ignored temporary file is logged without undoing publication.

Drafting is not a write. The daemon tells the model what a card is, the
folders this project offers in the card's own spelling, and the tasks the
project already loads with their schedules, then the conversation as the page
sent it; the page is the only thing holding that conversation, and nothing of
it is stored. The model is asked, with an example, to end a proposal with one
fenced block labelled `poieo-task` holding JSON, which the daemon reads as
YAML and takes out of the prose. Smaller models answer in a `json` or `yaml`
fence or with the bare lines, so any fence, and then the whole reply, is read
the same way; a card is a mapping with a name and a prompt, which prose never
parses to. A folder given by its listed name rather than its card spelling
(`src` for `../src`) is re-spelled; one outside the project, or one the list
does not have, arrives blank, as does a schedule the card could not take,
because the prose is still the answer and the person still chooses the
folder. `task_writer` resolves through `default` when the models file does
not name it -- see [binding.md](binding.md).

Structured editing is offered only when it can reproduce every field and
comment, which since the form gained a schedule line includes a one-line
`every:` or `at:` but not a `trigger:` block; otherwise the client edits the raw file. Set-aside and rename place an
immediate hold on the old runner, while the folder scan or next restart
reconciles the resident roster. Every card write knocks: the daemon's next look
at the folder is immediate rather than at the end of its scan interval, so a
card made, switched, renamed or set aside from the board is on the board before
the reader has moved. The write itself loads nothing; the scan stays the one
door a card comes through.

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
handoffs, and graph shape, and for the newest run its timeline event by event
from its start, bounded to the newest 400, so a drawer can follow a run as it
acts without a second transport. Unknown events are ignored so an older bundle keeps
working with a newer daemon.

The page's root type size follows the window's width, 16px up to a laptop's
and 22px from a large desktop's, and the bar, panels and buttons are
sized in em or rem so they follow it. The board magnifies by the same factor
and no further. Its initial view keeps a readable lower limit; fitting the
whole board can shrink a wider or taller graph further.

`App.tsx` owns project selection, the memory place, and the single active side
panel: task detail, models, chat, task creation, or closed. A card made from the
creation panel opens in its drawer as soon as the listing carries it; until
then the panel stays and says what it made. It shows one project's
stage at a time and keeps only view preferences in local storage. Everything global is one
bar, and the four kinds of thing on it have four looks: the places that take
the whole stage -- board, runs, and memory -- are tabs, with the current one
marked; the panels -- chat and models -- are toggles that show whether they
are open, and opening one never moves the tabs' mark, because a panel is over
a place, not a place; the daemon's connection is a dot, with the word for a
screen reader and the tooltip; and the theme is an icon. Under the bar the
stage leads with the place's own line: its name, how many tasks are on it,
and the acts that land on it -- `new task` sits there on the board only (the
empty board offers it in its invitation instead). Below a laptop's width the bar
wraps into two rows, everything after the name as one group in the same
order the keyboard reaches it, and a panel starts below both. The task
drawer leads with whether the reader must act and the latest or selected run's
result, time, duration, change, or usage -- and, for a change that was checked,
whether it was applied, is waiting for review, or was not applied, with the
checks folded behind that verdict: each command, its exit code and what it
printed, a refusal with every check green said in words, and the repair the
task tried first when there was one -- then what its prompt was made of --
the page and the memory entries against their budgets, the journal by size,
with the same gauge the memory view uses -- and which memory it was shown. In
the activity, a turn that knows its window puts its input tokens against it;
one whose window nobody could say keeps the plain count. The newest run's activity is the stage's own
timeline, followed as it comes rather than fetched, and it opens by itself
while the run is in flight; an older run's activity is fetched when opened.
Each tool call leads with the model's short purpose, while its exact recorded
input and result stay in a closed disclosure, and two or more tool calls in a
row fold into one line that says how many and what for -- open for the newest
group while the run is in flight, closed otherwise. The card's tool lines say
the model's purpose for each call when it wrote one. Older calls without a purpose use a conservative description from
their tool and subject. Full history and `Task setup` remain closed below;
selecting an older run keeps that run in view while live summaries continue.
A plain card's form is the new-task panel's, in its order: prompt, name, where
it works from the folder list, and when from the same plain-word choices
(a line they lack opens as written; `at another time…` opens the line the
task has rather than blanking it). Below it, `file name` moves the card's
file, which is the task's identity; `name` is only its title.
It carries its on/off switch beside those fields, sent
only when it moved; because the folder scan adopts that field without a
restart, the saved line then promises the daemon's next look rather than the
next run, and a switched-off task's controls point at that switch.
Above Task setup, **When it finishes** lists what this task starts after a
run -- the other task's title and the condition in words -- and adds one from
a list of the project's other tasks and four conditions: whenever it finishes,
if it succeeded, if it failed, or if its answer says a word. A condition
written by hand shows its label and is sent back unchanged. Any card can be
connected, including one edited as a file, and the wire appears on the board
at the scan's next look without a restart.
Inside the run's own box, one closed line says what it started with from
memory: the count and how many shaped the answer. Opening it lists one row
per entry with its opening words and what became of it, the ones that shaped
the answer first; each opens the memory place on that entry. Shared action
handling prevents a double press from issuing two mutations and keeps refusals
visible as results.

The new-task panel opens on one question: the conversation, with the fields
put away until a draft arrives or the person chooses `or write it yourself`.
A seeded panel (make one like it) opens on the fields. Each message sends the
whole conversation to the draft route; the reply is shown under it, with the
model that answered named once. A reply carrying a card shows that card --
its name, where it works, when it runs in the words the form's `when` list
uses for the same line, and its prompt -- and offers `use this draft`, which
brings the fields out and fills the name and prompt, the folder only when the
draft names one inside the project (the list keeps what it had otherwise),
and when it runs -- a schedule the choices have is chosen, any other opens
the line with it written out -- and says so above the fields. Enter sends,
Shift+Enter breaks the line, and Enter during input-method composition does
nothing. A refusal stays on screen with
the message still in the box, so nothing typed is lost. The conversation lives
in the panel and goes with it. The thread is capped in height so the box under
it stays put, and it scrolls to keep its newest turn in view -- the message on
its way, then the reply -- with the least movement that shows it; taking a
draft, or choosing to write by hand, brings the fields into view the same way
before focus lands on the prompt.

The chat panel is a conversation with the project, and a conversation is a
task: the project's chat card (`chat: true`, see `tasks.md`), which the panel
makes with the create route the first time a message is sent -- in the
project's own folder, able only to look. Each message starts one of its runs
with `{message, thread}`, and the runs that share a thread are the
conversation: the header's picker names each by its first message, most
recently spoken-in first, and `new conversation` starts another; opened with
none chosen while one is being answered -- after a reload, say -- the panel
shows that one. A conversation is read back from the task's run records in the
stage, so it is there after a reload and in the next session -- as far back as
the stage's window of the chat's newest fifty runs reaches. A first message
said before the card exists is held by the shell and sent once the daemon has
picked the card up, so closing the panel meanwhile does not lose it, and a
refusal then is shown when the panel is next open. A message the task is then
held back from answering -- a spend limit reached -- says why instead of
waiting. Each turn is a bubble, the reader's to the right and the answer --
the run's `said` -- to the left, with `what it did` folded under it: opened,
it fetches that run's events and draws its timeline. While the answer is being
worked on, the run's live timeline stands in its place: what the model says
between steps, which the drawer folds into the calls but the chat keeps, and
each tool it reaches for, folded, with a picture it looked at drawn small on
the call's line; a `working…` line closes it. `attach` picks pictures and text
files for the next message -- at most four, checked against what the daemon
takes before anything is sent, shown as chips that can be taken back -- and
they ride with its run-now; a sent message draws its pictures small and its
text files by name, from the files kept with its run. Words for a run already
going carry none. The header's permission picker says what the chat may do --
read only, ask each time, accept edits, allow all -- and writes it into the
chat card through the permission route; the next message runs under it, and
choosing allow all says plainly that commands then run on this machine
unasked. A call the answer is waiting on appears on its timeline as what the
step wants to do, with allow and deny, which answer it through the approve
route; once answered the line says which, and the drawer shows the same line
without the buttons. An answer that changed files in a project with private
copies says which, under its bubble, and while the change waits offers accept
up to this run and discard from this run onward -- the review's own control,
and the one place the chat task's changes are reviewed, since the board leaves
the task off; once decided the line says taken, thrown away or undone. Every
conversation's changes wait in one line, in the order they were made, so a
decision can reach another conversation's change; when it would, the line says
how many it would also take or throw away before either is pressed. What the
model thinks is never shown in the chat; a task's thinking stays in its
drawer. A message sent while the answer is being worked on is direction, heard
at the run's next model turn and drawn on the timeline as `you said`. The
stage keeps the chat's task, so its live events arrive, and leaves it off the
board: it is not drawn, counted, or offered as a place to hand work to. While
another task runs, a picker in the header names it: chosen, that run's
timeline is the thread, live and folded, and the box sends it direction; when
the run ends the box goes back to the conversation. The timeline itself lives
in `detail/Timeline.tsx`, read by the drawer and the chat alike. Enter sends,
Shift+Enter breaks the line, and Enter during input-method composition does
nothing. A refusal stays on screen with the message still in the box. The
shell holds which conversation is open rather than the panel, so a task picked
off the board -- which takes the one margin -- does not close it; switching
project does. An answer that came back empty says so instead of showing a
blank, and a failed run shows its error under the turn.

The fields are a prompt and a name, and the name may be left blank: it is then
the first line of the prompt, cut at the first sentence when that comes
within sixty characters and at the last word that fits otherwise, shown as the
field's placeholder before it is used and checked for collisions like a typed
one. Under `more` are where it works and when it runs. The
folder is a list standing on the whole project, `..`, offered as "this
project". When it runs is a list of plain words -- every hour, every 30
minutes, every day, every night at 2, only when another task starts it
(`manual`, for a task connected after another) -- each carrying the card's own line,
with a last choice that opens that line for an interval, the word loop, or a
cron line; blank sends nothing and the card takes its hourly default. How
changes reach the project is not asked: a new task starts under review, and
Task setup is where automatic application is switched on. The sentence above
the save names the folder that will change and whether there is a copy, and
it is there before anything is typed. Failed saves retain the whole draft;
successful saves clear it.

Under the question, before the first word, three example sentences stand as
buttons; pressing one puts it in the box to be changed or sent, and spends
nothing. A refusal that names the model -- no models file, a role that
resolves to nothing, an endpoint that did not answer -- carries `open models`,
which opens the models panel in the panel's place.

Work described in stages -- test, then fix if it failed, then report -- may
come back as a chain of up to four cards, each after the one that starts it.
The thread lists them with when each runs and offers `use these drafts`,
which puts the chain in place of the fields to be read over with the same
sentence about whose files change. Saving makes the cards last first, each
written already connected to the card it starts, so the first task cannot
finish a run before its followers exist; the quiet press leaves only the
first switched off. A refusal part way says which cards were already made.
Each card is then an ordinary card: its setup form shows it, and its
connections are kept through a form save and edited under When it finishes.

Steps are not written here. The step form that compiled drop-downs to the
graph schema is gone from the tree (git history has it); the daemon's steps
route and validation are unchanged, and until the board hosts the graph
canvas, a task of several steps is drawn in the standalone editor.

A card whose task applies its checked changes itself says so on its face, with
the checks on the tooltip. Fresh listings update this permission and its checks
on an already open board. A run list row carries one recorded outcome, including
applied, already included, discarded and undone; completed decisions are not
counted as waiting for review. The run brief keeps that outcome on its time line
and shows each verification command once below it. A check that modifies the
prepared copy explains that refusal even when its exit code was zero. Unfinished
checks retain their output, and a repair refused before starting says why
without claiming it ran.

Task cards start collapsed, showing a compact **Start / Input → step count →
End run / Output** flow -- left out for a one-step task nothing is connected
to, where it would say only "1 step". The card's name, marked with a `›` and
underlined on hover, opens the task; **Expand**, a bordered button at least
28px tall, reveals only that card's full graph, live text
and tool calls; **Collapse** gives its space back. The chosen state survives live
updates, and running a task never opens its card automatically. Status and standing
warnings remain visible in either state. Handoff wires keep connecting the visible
Output and Input when either card expands or collapses; following a wire leaves
the receiving card's chosen detail level intact.

An expanded task card shows a vertical graph with **Start** and **End run** terminals,
even for a single step. Arrows point into the next step and small dots mark the
source of each connection; return paths use dashed lines. These are execution
connections, not data inputs or result values. Conditions stay on their own
amber wires, even when two choose the same step. When several conditions are tried,
their labels show the authored priority (1, 2, …), independently of their spatial
placement: the first matching condition wins. The otherwise
path always appears, including when it ends the run. Step names wrap, and repeated
descriptions include IDs to distinguish destinations.

Task handoffs continue through the card graphs: every possible **End run** feeds
one **Output / Run result**, and the receiving card's **Input** leads to its first
step. The output is the completed run's results, state and answer received as
`input.sender`; it does not claim that a particular last node supplies a particular
field. Question endings say **After answer** before Output. A null task handoff
ends at **Stop here**. Several conditions to the same task share a board wire and
retain their authored priority. Only tasks in the sender's project can receive it.

Tasks joined by handoffs are a flow, and each flow is a band at the top of the
board in the order its first task is listed: each task one column past its
furthest sender, on the row of the sender that starts it or the first free row
below. Tasks nothing joins stand in a grid under every flow, as wide as the
window allows; with no handoffs at all the whole board is that grid.

Board wires attach to the measured Output and Input, even after pan/zoom or a card
resize. Forward wires use the gaps between columns; a forward wire that skips
columns runs straight along its own row when no card in the columns between
stands on it. Returns are dashed and run below the cards, as do skipping wires
something stands in the way of. Hovering or focusing a
terminal or wire highlights its connections and both cards. Clicking a wire, or
pressing Enter/Space on it, brings the receiving card into view and focuses Input.
Title updates preserve focused terminals and wires while allowing the board to
remeasure a wrapped title. A wire's word is the connection's label, and the
board's own conditions are said as the task panel says them -- `always`,
`succeeded`, `failed`, or the word an answer must contain -- rather than as the
expression. The task open in the panel is ringed on the board, and opening one
moves the board only as far as it takes to show that card whole.

Expanded card graphs measure their labels before Dagre places nodes from top to
bottom. Expanded connected cards grow to fit the complete graph without internal
scrolling or scaled-down labels. Column widths include the widest card so wires clear the
other cards too. Independent cards wrap conditions more narrowly when needed;
their graphs never scale below 90%, and unusually wide forks or graphs taller than
460 pixels scroll within the card. Diagram terminals are separate from authored
step IDs, so a step named `start` remains an ordinary step.
The initial board view keeps cards at a readable scale, fitting at least one
card's width on narrow screens. Dragging and the minimap reach tasks outside
the viewport; double-clicking the board background fits the whole board.

Within an expanded card, **View steps** opens a native dialog outside the board's
pan/zoom transform, with an independent scrollable canvas, zoom controls, fit, and a 100% reading
size. Nodes use authored descriptions, an entry marker, model assignments and
explicit endings. Dagre lays this graph out from left to right, reserves space
for wrapped conditions, and retains a separate edge for each branch.
The router's otherwise path is always drawn, including an omitted default that
ends the run; return paths retain their arrows. Conditional paths are amber.
Running-step updates highlight both views without rebuilding their steps or
resetting their scroll or the chosen zoom. Removing the task closes the dialog,
and closing restores focus to its opener. Narrow screens use the full viewport.

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
and a word both say when a value is near or over its limit. The page editor
counts its draft the same way, as a run reads it with comments removed, and
never refuses to save over the budget: the page must not become a way to stop
every task. The evidence pane is also where a person
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

The board shares the persimmon logo and paper, ink, and gold palette with
the website. `index.css` defines both themes; components use its named colours
so status stays distinct from the gold review accent. `ThemeSwitch` follows the
system preference until the user chooses Light or Dark, saves that choice in
`poieo.theme` for the browser origin, and updates the browser's theme colour.
Storage failure does not disable switching. The logo changes with the theme.
The memory canvas also repaints its colours, preserving the current orbit,
zoom, and selected entry.
Hanken Grotesk and DM Mono ship with the board for offline use; decorative wash
art and serif headings belong to the public website, not the working board.
The visual reference and asset list live in [the brand guide](../brand/README.md).

The plain-card editor exposes review or automatic application, allowed paths
and verification commands in an optional disclosure; the new-task panel does
not, since a new task starts under review. Automatic mode requires explicit
selection and at least one check. Run history displays
the application outcome and verification output, including repaired, already
included and undone work. Applied diffs use the final verified combination.
An applied run offers undo through the same checks; unresolved undo leaves the
project intact. Optional direction goes through the task's `/note` route: to the run in
flight, which hears it at its next model turn if it has one (`delivered`; the
journal keeps the words either way), or else kept for the next run (`saved`);
the form says which. On the timeline the words appear as
`you said`, where the model heard them. Successful application decisions announce a fresh task listing so
all open boards update pending counts, holds and their reasons together. Fresh
listings replace or clear previous hold reasons.

Any change under `web-ui/src/` must rebuild and commit
`src/poieo/web/static/` in the same PR. See [contribution.md](contribution.md).
