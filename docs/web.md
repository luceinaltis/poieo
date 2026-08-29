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
| `GET /api/projects/{p}/models` | every model this project can reach, asked live, endpoint by endpoint |
| `GET /api/events` | every event, live (SSE; `?task=` filters) |
| `POST /api/projects/{p}/tasks` | **make** — write one card into the tasks folder |
| `POST /api/tasks/{p}/{f}/accept` | **review** — put the work in the user's own branch |
| `POST /api/tasks/{p}/{f}/discard` | **review** — throw it away, recoverably |
| `POST /api/tasks/{p}/{f}/pause` | **control** — hold the schedule |
| `POST /api/tasks/{p}/{f}/resume` | **control** — rearm it |
| `POST /api/tasks/{p}/{f}/run` | **control** — one fire, now |
| `POST /api/tasks/{p}/{f}/answer` | **answer** — decide what a `confirm` node asked |
| `POST /api/projects/{p}/models/use` | **models** — point a role at another model |

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

**Models** is a fourth kind, and it should be the last one anybody argues for.
It writes a file the user keeps, so it is not control — control's own rule is
that nothing it does survives a restart. But the file is not the *work*, so it
is not the review either: review moves what a model wrote into the user's own
branch, and everything it touches was written by a run. This touches one file
the user chose and poieo generated, rewrites the two lines it came for, and
leaves every other byte — comments included — exactly as they were; it is the
same edit `poieo config use` makes, through the same `rebind.point_at`, which
is why there is no second set of refusals to keep in step. Its own fence: **it
may write the project's binding file and nothing else, and it never accepts or
returns a credential.** A key is a variable *name* here and a value nowhere. If
a route in this group ever needs to take one, that is the signal this kind has
stopped being what this paragraph describes.

`GET /api/tasks` carries `asking` — `{run_id, question, choices}`, or null. The
route needs it: without it the answer route is a button with no label on it.

### `GET /api/projects/{p}/models`

**Every model this project can reach**, endpoint by endpoint, with whatever each
endpoint said about each model. Not what the project is *bound* to — that is one
line of the answer and the smaller one; the question this opens for is "what
could I be running, and what would it cost".

**Asked live**, for the reason `poieo config models` is asked live: a catalogue
written down a month ago has since gone wrong, and a model named from memory
fails at 3am. Every endpoint is asked at once through `detect.catalogue_for` —
two asked in single file is two `HTTP_TIMEOUT`s on a laptop where neither is
running. The handler is already on the daemon's loop, so it **awaits**;
`asyncio.run` from here raises, and `cli.py` is full of it, which is why the
catalogue is shared as a coroutine rather than as a copied body.

It is addressed by **project**, not by task, because that is `poieo config`'s own
scope: the endpoints belong to the project, and hanging the answer off a task
would put the same answer on every card. `_project_for` is the lookup, and a name
that answers for nothing is a **404 carrying the names that do** — the board
remembers a project across restarts, so a picker holding one the daemon was
started without is a real state rather than a typo.

`_models_of` decides *which endpoints to ask* from the spec **already in
memory**, off any task bound to the project's own file. Reading the file instead
would let the panel ask a different set from the one the board is painting the
moment anybody typed `poieo config use`. One truth per screen; a run re-reads
the file and moves both together (see [daemon.md](daemon.md)). It falls back to a
read only for a project whose every task is disabled or bound elsewhere.

Each model carries `id`, `ref`, and whatever the endpoint published: `context`,
`size`, `quantization`, `capabilities`, `price`. **Every one of those is null
when the endpoint did not say**, and none is filled in from anywhere else.
`price` is the one worth stating plainly: [runtime.md](runtime.md) refuses a
price table in this repository — *"nothing in poieo knows what a model charges,
and a price table checked in here would be wrong the week after it was
written"* — and this does not add one. OpenRouter publishes per-token rates on
the same listing it publishes ids on, so those are reported, converted to USD
per **million** tokens because `0.00000015` is not a number anybody compares at
a glance. Every other OpenAI-shaped server publishes none, and Ollama charges
nothing per token at all; both come back null, and the panel distinguishes them
by the endpoint's type rather than by inventing a zero.

`used_by` is the one thing the binding contributes: which roles are on this
model, so a reader can see what they are using among what they could. A list,
because a model may serve several.

Two things deliberately do not cross. A **key** never does: only the name of the
variable it comes from, and whether that is set — read through
`providers.credential_for`, so the rule about where a credential comes from stays
in one place and the value never reaches this module to be leaked. That name is
not decoration: an endpoint whose key is unset lists nothing, and it is the whole
explanation. `api_key_set` is **null rather than false** when an endpoint names
no variable, because "its SDK resolves its own" is a different fact from "the key
is missing", and a panel warning about the first would cry wolf on every local
endpoint. And a **`base_url`** does not cross either: an endpoint's own name
tells one from another, and an address is the one field in a binding that can
carry a private host. If a real confusion turns up — two `openai_compatible`
endpoints a reader cannot tell apart — the argument for letting it through will
be concrete.

### `POST /api/projects/{p}/models/use`

`{target, role}` — a `provider/model` reference and the role to point at it,
`default` when the body names none. It answers `{status: "using", role, ref,
checked}`.

**Every refusal is decided before `rebind` opens the file**, so a request that
will be refused never touches it — and `rebind` itself refuses before writing on
any shape it does not recognise. In order:

| code | when | carries |
|---|---|---|
| **404** | no such project | the names that do answer |
| **400** | `target` is not `provider/model` | — the argument is malformed, not the state |
| **409** | this project declares no such endpoint | the ones it does |
| **409** | the endpoint answered and does not serve that model | what it does serve |
| **409** | `rebind` will not edit that shape | its own sentence, naming the file and the key |

An endpoint that **did not answer does not block the edit**, exactly as
`poieo config use` allows: a laptop with its server switched off still gets to
edit its own config. `checked: false` says so out loud rather than implying a
check happened — silence from an endpoint is not its agreement. The key is not
checked either, for the same reason: pointing a role at Claude before exporting
the key is a legitimate order to do things in, and the panel already shows that
the variable is unset.

**`status: "using"`, not `"changed"`.** *Change* is one of the user's three words
and already means what a run did to the files.

**The write rereads.** `daemon.reread()` runs after `point_at` returns, because
the board draws each node's model off the spec in memory — without it the file
and the picture part company the moment somebody clicks, and the reader is
looking at two answers to one question. `roles` on the read report is what the
panel may offer: `default` plus the roles the file already names, and **not**
every role the graphs call, because offering one the file has never named is how
a panel creates the misspelled role `binding.md` spends a page warning about.

`askable` is the third fact an empty list can mean: `mock` answers from the
binding file, so there is nothing to ask, and a panel that ran that together with
"did not answer" would report a working endpoint as a broken one.

`label` is what a person would recognise the endpoint as — "vLLM", "SGLang",
"OpenRouter". `type` alone said nothing: `openai_compatible` is all of those at
once. `detect.label_for()` prefers **what the server said about itself** on its
own listing, falling back to the address; [storage.md](storage.md) has the
sources and why they are in that order. The **address itself still does not
cross**, only the name it produces, and `label` is null when nothing answered
the question — the panel falls back to the type then.

**The panel leads with what answered, not with the key in the file.** A
provider's key is the handle its author typed; reading a config back to somebody
is not telling them what is there. So `OpenRouter` is the heading and `routed`
sits beside it, and only when nothing identified the endpoint does the key lead.

`installed` is the difference between two listings that look identical.
Ollama's `/api/tags` is `ollama list` — models pulled onto *this disk*, ready
now, and all of them. OpenRouter's is a catalogue of what it would route to for
money, with nothing here yet. `detect.lists_installed()` is the one place that
knows which is which, so the panel does not decide it from a type string of its
own.

**The route asks with `limit=None`.** `MODEL_CAP` is a sensible default for
`init`, whose job is to fill a picker — *"a server offering hundreds is a
catalogue, not a choice"*. This panel **is** that catalogue: OpenRouter answers
with 396 models, and forty of them shown without a word reads as all of them.
The cap stays the default on `catalogue_for` and this is the caller that lifts
it.

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
  models/           which models this project runs on
```

**`Models` is reached from the rail, not from a card.** A project's models are
the project's, and putting them in the drawer would repeat one answer on every
task.

The **rail** is the nav down the left: what the page is *for*, where the bar's
controls are a fixed handful about the board already on screen. It holds `board`
and `models` today and is where the next view lands. `board` is a rail item
rather than a close box, because "no panel over it" is a place you can be and
closing is not — the rail always says where you are, in one item marked
`aria-current="page"`.

The panel itself is the drawer's twin — the same fixed aside on the same edge at
the same width — so only one of the two is ever open, and `.shell-stage` reserves
one margin for whichever it is. Its width comes from `--rail-width` on the left
and the drawer's constant on the right; the rail is `position: fixed`, so the
stage has to reserve exactly that much or the board slides under it.

**A big catalogue folds by maker.** A hosted listing names every model
`maker/model` — 396 across 58 makers — and a flat list of that is not read, it
is scrolled past. So each maker is a `<details>` card, shut until opened, with
its count on the summary; a filter opens them, because the matches are what was
asked for. Inside a card the rows drop the prefix the card already says, with
the whole id still on the tooltip since that is the half of `ref` a reader
copies out. The test for whether to fold is mechanical — every id carries a
prefix, and there are at least `WORTH_GROUPING` of them — rather than a list of
endpoints known to have makers, so an endpoint that grows into that shape gets
it without anybody deciding. What is *on a machine* is named the way its owner
pulled it (`qwen3.5:latest`, `hf.co/user/repo`), where a leading segment is a
host or nothing at all, so those stay flat.

**The panel filters rather than truncates.** A four-hundred-model catalogue is
read by narrowing it, and the count keeps saying what it narrowed *from* — "12
of 396 offered" — so the filter does not become the same silent truncation it
replaced. An endpoint with nothing matching leaves the list entirely: left in
place it would show "no answer" under its own heading, which is a different and
more alarming thing than a search that missed.

**The row is the button.** A catalogue is read by scanning names, and a verb
beside each of four hundred of them is four hundred words the eye has to skip.
What a click moves is chosen once, above the list — and only where there is a
choice, since a project whose file names no roles has one answer and a picker
with one option in it is furniture.

**A row is what the endpoint said, and a blank is what it did not.** A local
model shows the two numbers that are its real price -- its size and
quantization -- and says it *runs here* rather than showing a rate of nothing; a
routed one shows the rate it published. An endpoint that charges but publishes
nothing leaves the column empty, because "free" would be a guess and an
expensive one to be wrong about.

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

**Making a card is the fifth kind of write**, and the first that creates a file
that did not exist. Its fence is one card in the project's tasks folder: no
graph, no binding, and no path out of that folder — the name is turned into a
filename here rather than taken as one, and a name that reads like a path is
refused rather than quietly rewritten. It takes the three things DESIGN.md says
a task cannot do without and no fourth, and the folder is required because it is
the one thing the model's hands will touch.

There is **no reload call behind it**. The daemon watches that folder, so the
route's whole job is the file; one door rather than two that must agree.

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

- **The page that would call it.** `POST /api/projects/{p}/tasks` exists and
  writes a card the daemon then finds, the way it finds one written by a hand —
  but nothing in `web-ui/src/` calls it yet, so from a browser this is still an
  API and not a button.
- **Editing and removing a card.** Changing a card's name or folder, and
  deleting it, still mean editing the file.
- **The canvas editor folded in.** `editor.py` and `viewer.py` render a graph as
  a standalone page today (`poieo edit`, `poieo view`, `poieo show --mermaid`);
  the board does not host them.
