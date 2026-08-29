# Web — the API and the page

`src/poieo/web/` (server, event fan-out, the built page) · `web-ui/` (its source)

While `poieo daemon` runs it serves a page on `http://127.0.0.1:8484`
(`--port` to change it, `--no-web` to turn it off). The page ships built under
`src/poieo/web/static/`, which is deliberately checked in — there is nothing for
a user to install.

## The API

Almost everything answers *what is happening / what happened*. The routes that
change anything come in exactly **two kinds**, one fence each, and both the
server and the client keep them together so they stay easy to count.

| route | does |
|---|---|
| `GET /api/tasks` | every project on this board, then every task: which project's, status, trigger, last run, how much is waiting for review, and its wiring |
| `GET /api/runs` | run summaries, newest first (`?task=`, `?project=`, `?limit=`) |
| `GET /api/runs/{id}` | one run's whole event stream |
| `GET /api/runs/{id}/diff` | what that run changed |
| `GET /api/events` | every event, live (SSE; `?task=` filters) |
| `POST /api/tasks/{p}/{f}/accept` | **review** — put the work in the user's own branch |
| `POST /api/tasks/{p}/{f}/discard` | **review** — throw it away, recoverably |
| `POST /api/tasks/{p}/{f}/pause` | **control** — hold the schedule |
| `POST /api/tasks/{p}/{f}/resume` | **control** — rearm it |
| `POST /api/tasks/{p}/{f}/run` | **control** — one fire, now |
| `POST /api/tasks/{p}/{f}/answer` | **answer** — decide what a `confirm` node asked |

**Review** routes are the only ones that may ever touch the user's own files. If
you are adding a third of them, stop. **Control** routes touch the daemon's
runtime state and nothing else: no file, no schedule on disk, nothing that
survives a restart.

**Answer** is a third kind and only looks like control. It touches none of the
user's files, so it is not review — but it removes the question kept under
`runs/asking/`, and the `then:` it releases can set a chain of tasks going. It
is the one route whose effect outlives the process, which is exactly what a
person deciding something is for. Its refusals are worth reading: **409** when
the task is there but has no question open, so a board holding a stale button
can tell that from a **404**; and **400** with the choices that *were* offered,
because whoever asked is holding a list that has moved on.

`GET /api/tasks` carries `asking` — `{run_id, question, choices}`, or null. The
route needs it: without it the answer route is a button with no label on it.

`create_app(daemon)` takes a daemon-shaped object (`.runners`, `.store`,
`.config`), which
is what makes the API testable without a running daemon. `.store` answers for
every project the daemon runs — one store when there is one project, a
`MergedStore` over their stores when there are several — so no route here knows
how many there are. `.config` is still the first project's; the routes are not
project-aware yet, which is also why the daemon refuses to start two projects
that share a task name.

### Whose board this is, and whose task

`/api/tasks` answers `{projects, tasks}`. `projects` is a list, because a daemon
runs as many as it was given, and it rides on the listing rather than on each
row because the listing that most needs naming is the empty one — with no tasks
to recognise, one daemon's page is another's. With exactly one the page puts its
name in the bar and in `document.title`, since two boards open side by side are
two tabs, and hangs the folder off the label as a tooltip: two worktrees of one
repository can share a name, but not a path.

**The board shows one project at a time.** With several, the bar's name becomes
a picker; with one it stays a name, because a picker with one option in it is
furniture. There is no "all": two projects side by side share nothing but a
machine — no arrow crosses between them — so all of them at once is a wall
rather than a board. The choice is remembered like the skin is (`poieo.project`
in `localStorage`), and a remembered project the daemon was restarted without
falls back to the first rather than leaving the board filtering on nothing,
which looks exactly like broken.

**A task's identity is its project and its name**, and every route that names
one takes both. A name alone stopped picking out one task the moment a daemon
could run two projects, and every project has a `chores`. The page keys its
board on `` `${project}/${task}` `` — built by `keyOfTask()` and never split,
because whoever needs the halves has them already — and shows the plain name on
the card, since the project is the board's business and not the reader's.

The daemon refuses to start two projects answering to one name, which is what
makes the pair an identity rather than a guess. A run summary written before
this carried no project, and `_runner_for` treats that `None` as "whichever task
has this name" rather than losing the diff over a field the record never had the
chance to carry.

### The wiring on `/api/tasks`

Two fields carry what a view needs to *draw* the work, with no new route and no
second fetch — the tasks route already had the graph in hand:

- **`then`** — which task works next, and the word on that arrow
- **`shape`** — `entry`, and each node's `next` / `branches` / `default` /
  `model` / `tools`

Both arrows have **one shape**, because a router's branches and a task's `then:`
are the same `Branch` one level apart: a view that can draw one can draw the
other, and a reader learns one arrow rather than two. A branch with no label is
drawn with its condition — the same fallback `RouterNode` uses when it records
which arm it took, so the board and the run record never disagree about what to
call an arrow.

`model` is the id the node **would actually call**, resolved exactly as
`runtime/nodes.py` resolves it (`binding.resolve(node.role or
graph.default_role).model`), so the picture cannot claim one model and the run
make another. It is `null` for a router, which calls none. Per-node `params` are
deliberately not applied: they layer generation settings onto a role, never a
different model. This is why `_shape` takes the `LoadedTask` and not the
`GraphSpec` — a role resolves against a binding, and the same graph under two
bindings is two different afternoons.

`tools` is which toolsets the node may use, and so **whether it can reach the
folder at all**. It is the one field here that is not about drawing: two agent
nodes are otherwise the same picture — same type, same model, same box — and
one of them rewrites the project while the other only answers. A board that
cannot tell them apart asks the reader to guess at exactly the thing
`DESIGN.md`'s safety boundaries say they should never have to. It crosses as a
**list, never absent**: `None` and `[]` both mean no hands, and a field a view
can forget to read is one whose absence draws every step as harmless.

`shape` is deliberately **not** the whole `GraphSpec`, and little more than the
bare model id and those toolset names crosses. Prompts and system messages are
long, are of no use to a drawing,
and this rides every board paint out to every browser watching; a graph's text
is exactly the sort of thing a person would be surprised to have broadcast. A
`ProviderSpec` knows a `base_url` and the name of the variable its key comes
from, and a drawing needs neither — a test holds that line, so the next field
added here has to argue for itself. A node's `ui` coordinates are **absent
rather than zeroed** when the editor never placed it, so a view that lays out
unplaced nodes itself can tell "at the origin" from "nowhere yet".

### Answers, not exceptions

- a run that altered nothing returns `{"change": null}` — that is an answer, not
  a failure
- `accept` refused because the checkout is dirty, or because of a conflict,
  returns **409 with the paths**; a refusal is information the reader needs
- `run` refused because a run is in flight returns 409 naming that run —
  iterations never overlap, exactly as the triggers promise
- a successful `run` answers `"starting"`, not `"running"`: the runner picks the
  fire up on the next turn of the shared event loop, after the response is gone

### Off the loop

The daemon, the web server and every task share one asyncio loop, so anything
blocking is wrapped in `asyncio.to_thread`: the git work behind `diff`, `accept`
and `discard`, and the index scan behind `run()`. `/api/tasks` gathers the
per-task review states **concurrently** — each is two git subprocesses, and asked
one runner at a time the board's first paint would wait for all of them in single
file.

## Event fan-out

`BroadcastStore` wraps a `RunStore`: writes go through to disk and are also
pushed to live subscribers (asyncio queues on the daemon's loop).

**The store never waits on a subscriber.** A full queue means the browser stopped
reading, so that subscriber is evicted; `EventSource` reconnects on its own.

It subclasses `RunStore` to *be* one where a `RunStore` is expected, but **every
method routes to the wrapped store, reads included**. Inheriting the reads made
them read `self.root` instead, which is only the same file by accident — over a
`NullStore` the wrapper answered the web API from whatever `runs/` the daemon
happened to be standing in.

`run_tasks` maps run id → task, learned from `run_started`, so the SSE endpoint
can filter by task without parsing every payload.

Static assets are served immutable (Vite emits content-hashed names), while
`index.html` is `no-cache` — that document names the build, and a cached one
would leave the reader running an old page with no way to find out.

## The page

```
web-ui/src/
  api.ts            everything that talks to the daemon
  shell/stageStore  fetch history, open the stream, hold the model
  state/stage.ts    the one place run events are interpreted
  skins/            how that model is drawn — atelier, basic
  skins/wiring.ts   where a work graph's containers go; pure, and tested alone
  detail/           the drawer: one task, turn by turn, plus control
  detail/Question   what a `confirm` node stopped to ask, and its answers
  review/           last night's work: the list, the diff, accept and discard
```

**`Question` is drawn first in the drawer, above the controls.** Everything
after a `confirm` node is held until it is answered, so a reader who scrolls
past it is looking at a flow that has quietly stopped. It has no confirmation
step, unlike `Decide`: the graph's author already wrote the question, and
asking "are you sure?" over the top of somebody else's sentence only makes it
easier to stop reading it.

Like accept and discard, it lives in the drawer rather than on the card. The
board is a list of what is happening; deciding is what you open a task to do.
`poieo asking` is the way to see every open question at once.

**One reducer.** Live SSE frames and replayed history are the same bytes, so
they fold through the same function — replay is the live path at a different
speed. Everything downstream reads `StageState` and never an event.

**Skins are plain DOM behind a contract.** A skin renders a `StageState` and
takes callbacks; it never fetches, never sees a raw event, and keeps no state of
its own beyond what it needs to draw. If a skin needs to know something,
`StageState` is what is wrong, not the skin. `App.tsx` is the only file here that
knows React. Adding a skin is a module and a line in `skins/registry.ts`.

`mount()` is synchronous on purpose: a skin whose renderer has to be loaded
(atelier's three.js stays behind a dynamic import) returns its handle at once and
swaps the renderer in later. Making it a promise would push waiting onto the
shell and onto every future skin to serve one skin's private problem.

The chosen skin lives in `localStorage`. `basic` is the default, and is also
where a stale or unknown id lands rather than blanking the page -- so a reader
with nothing stored and a reader with something unreadable stored get the same
page. `atelier` is a click away.
`basic` draws the work as a graph — the tasks, their nodes, the arrows between
them, the model each node calls, and which of them have **hands**. That last one
is marked with the word rather than a glyph, and on every node that has them
rather than only when the nodes disagree, because unlike the model it is never
answered by some other step having said it. `skins/wiring.ts` is the part of that with
an answer capable of being wrong (where containers go, in what order nodes are read),
so it is pure and tested on its own; measuring containers and running an arrow
between two of them is arrangement, and jsdom has no geometry to check it
against anyway.

**Every write answers rather than throwing** (`Answer { ok, ... }`), so a
refusal — uncommitted edits in the reader's own project, a run already in flight,
a daemon that went away — travels the same path as a success.

## Working on it

```bash
npm run build --workspace web-ui   # refresh what the daemon serves
npm run dev   --workspace web-ui   # 5173, against a daemon on 8484
npm test      --workspace web-ui   # run mode — watch mode hangs an agent
```

`src/poieo/web/static/` **is** meant to be committed; `node_modules/` is not — and
committed in the same PR as the source it was built from, since neither suite reads
it and a green run says nothing about it. `docs/contribution.md` has the whole story.

## Not built yet

- **Task card CRUD from the board.** Observe, review and control are live;
  creating or editing a card still means editing the file.
- **The canvas editor folded in.** `editor.py` and `viewer.py` render a graph as
  a standalone page today (`poieo edit`, `poieo view`, `poieo show --mermaid`);
  the board does not host them.
