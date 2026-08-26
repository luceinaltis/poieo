# poieo

A harness for running LLM workflows where **what the work is** and **which model does it**
are two separate files.

A *graph* describes the logical flow: classify this, then branch, then draft a reply. It
names **roles** (`classifier`, `writer`, `critic`) and never names a model. A *binding*
maps those roles onto physical endpoints — Claude, a local vLLM server, Ollama. Moving a
workflow from a laptop model to Claude Opus 5 is a `--binding` flag, not an edit.

A *daemon* keeps flows alive on triggers, so the logical flow just keeps running.

```
graph (logical)          binding (physical)          daemon (resident)
  classify   ──role──►     classifier → ollama:llama3.2:3b     interval / cron / loop
  route                    writer     → claude:claude-opus-5
  draft_bug
```

## Install

```bash
pip install -e .          # or: pip install anthropic pydantic pyyaml httpx typer
poieo --help              # also runnable as: python main.py --help
```

## Start a project

A folder becomes a poieo project the way a folder becomes a git repository:
one marker file, `poieo.yaml`. `poieo init` looks at the machine once — an
API key means Claude, an answering Ollama means local, neither means mock —
and writes what it found into ordinary files:

```
poieo.yaml               store · default binding · tasks folder
bindings/default.yaml    what detection found (plus mock.yaml, always)
tasks/hello.yaml         a sample card, disabled; run it by hand
.gitignore               gains a `.poieo/` line
```

Inside a project, commands need no flags. `poieo run tasks/hello.yaml` takes
the project's binding (and says so), `poieo runs list` reads the project's
store, `poieo daemon` finds the config, `poieo check` probes the project's
providers. A flag always wins when passed; discovery only fills silence, and
detection never runs again after init — run time reads files, nothing else.
Existing files are never touched, so `init` in a full project changes nothing.

## Try it without spending a token

The `mock` provider answers from a script in the binding file, so the wiring can be
exercised offline.

```bash
poieo show     examples/graphs/support-triage.yaml
poieo validate examples/graphs/support-triage.yaml -b examples/bindings/claude.yaml
poieo run      examples/graphs/support-triage.yaml -b examples/bindings/mock.yaml \
               --set message="the export button crashes on 2.1"
poieo daemon   examples/poieo.yaml --once
```

A task card that names its own `binding:` needs no flags at all --
`poieo run tasks/card.yaml` runs it once, and `poieo daemon tasks/` keeps
every card in the folder running.

## The logical layer

```yaml
name: support-triage
entry: classify
nodes:
  - id: classify
    type: llm
    role: classifier                 # a role, not a model
    prompt: |
      Classify as bug, feature, or question.
      {{ input.message }}
    output: {as: category}
    next: route

  - id: route
    type: router
    branches:
      - when: "'bug' in category.lower()"
        to: draft_bug
    default: draft_answer
```

**Node types**

| type | does | keys |
|---|---|---|
| `llm` | renders a prompt, calls the model bound to its role | `role`, `system`, `prompt`, `output`, `retry`, `params`, `next` |
| `router` | evaluates conditions in order and jumps to the first match | `branches[].when` / `.to` / `.label`, `default` |
| `agent` | hands the model tools and loops until it finishes one step | `role`, `workdir`, `tools`, `max_turns`, plus the `llm` keys |

`next: null` (or an omitted `next`) ends the run. A `to: null` branch ends it too.

### Agent nodes

An `agent` node gives its model hands: `files` (read/write/list/glob) and
`shell` (run a command) toolsets, every call confined to the node's `workdir`.
The node loops — model asks, poieo executes, result goes back — until the
model answers without a tool call; `max_turns` bounds the loop. Tool failures
are fed back to the model as text so it can correct itself. Every call is
recorded as a `node_tool_call` event in the run log.

Path confinement prevents accidents, not malice: a shell command can still
name absolute paths. Point `workdir` only at a directory you would let a
junior contributor loose in — or turn on isolation, below. `poieo run
examples/graphs/agent-task.yaml -b examples/bindings/mock.yaml --set
workdir=/tmp/demo` exercises the loop offline.

### Isolation

A task can be told to keep its hands inside its folder:

```yaml
name: keep the tests green
folder: ~/src/thing
prompt: Run the tests and fix what fails.
isolation:
  image: python:3.12-slim    # must already be pulled; poieo never pulls for you
  network: none              # the default; `bridge` if the task needs to fetch
```

Without it, poieo's file tools stay inside the folder but a command the model
runs does not — it reaches whatever you can reach. With it, the command stays
inside the folder too. Nothing else changes: the same task without the block
behaves exactly as before, and a machine with no docker is never even asked.

`poieo run … --isolate python:3.12-slim` does the same for a single run.
Whether docker is present and the image is here is checked when the config
loads, not when the trigger fires at 3am.

The environment is kept between runs, so what a task installs on Monday is
there on Tuesday, and tasks over the same folder share one. It is disposable
state: `poieo reset <task>` throws it away and the next run rebuilds it, which
is the first thing to try when a task starts behaving oddly. Nothing in your
folder is touched by that.

**What it does not protect.** The folder itself — that is the work, and it is
exposed by definition; reviewing what a run changed is a separate feature.
What reaches the model, either: prompts and file contents leave your machine
exactly as before. And a container shares your kernel, so this is a strong
boundary rather than an absolute one; a VM is stronger.

The question it actually asks you is: *can you predict every command this
prompt will run, overnight, with this model?* If yes, isolation buys little.
If no, that is what it is for.

**Expressions** in `{{ … }}` templates and `when:` conditions run in a sandbox: attribute
and index access, comparisons, boolean logic, and a short list of builtins (`len`, `str`,
`any`, `sorted`, …). Imports, lambdas, comprehensions, and dunder access are rejected when
the graph is parsed, not when it runs.

Names in scope:

| name | is |
|---|---|
| `input` | the payload the trigger or CLI supplied |
| `state` | mapping that survives across loop iterations |
| `nodes.<id>` | any earlier node's output |
| `<alias>` | an output's `as:` name, at the top level |
| `run` | `id`, `flow`, `trigger`, `iteration`, `path` |

`output` shapes what a node stores: `as` names it, `format: json` parses the completion
(tolerating a markdown fence), `path: a.b` digs into it, and `into_state: k` also writes it
to `state` so the next iteration can read it.

**Cycles are allowed.** `examples/graphs/draft-review.yaml` loops draft → review → revise
until the critic approves, counting its own attempts with `run.path.count('revise')`.
`max_steps` bounds any graph that forgets to exit.

## The physical layer

```yaml
name: hybrid
providers:
  ollama: {type: ollama, base_url: http://localhost:11434}
  claude: {type: anthropic}

default:
  provider: claude
  model: claude-opus-5
  params: {max_tokens: 16000, effort: high}

roles:
  classifier:                       # cheap local model for one-word labels
    provider: ollama
    model: llama3.2:3b
    params: {max_tokens: 16, temperature: 0}
```

Role settings layer over `default`, and `params` merge key by key. A node's own `params`
win over both. Four bindings ship as examples: `mock`, `local`, `claude`, `hybrid`.

**Providers**

| type | talks to | notes |
|---|---|---|
| `anthropic` | Claude API | official SDK, always streams; credentials from `ANTHROPIC_API_KEY` or an `ant auth login` profile |
| `openai_compatible` | vLLM, SGLang, llama.cpp, LM Studio, TGI | `POST {base_url}/chat/completions` |
| `ollama` | Ollama | `POST {base_url}/api/chat`; `max_tokens`/`temperature` are folded into `options` |
| `mock` | nothing | scripted replies for tests and dry runs |

The Anthropic provider is capability-aware: `thinking: auto` becomes adaptive thinking on
models that support it and is omitted on ones that do not, `effort` is dropped where it is
not accepted, and sampling parameters are stripped for models that reject them — so one
binding can point different roles at different model generations without 400s. Unrecognized
params pass through untouched, so a new API parameter is usable from the binding file
without a code change.

Add a backend with `poieo.providers.register("my_type", MyProvider)`; binding files may
name it from that point on.

```bash
poieo check -b examples/bindings/local.yaml      # probe every declared endpoint
```

## The short form: a task

A graph plus a binding plus a daemon entry is three files. When the work is
*one model, one folder, one instruction, on repeat*, write one instead:

```yaml
# tasks/keep-improving.yaml
name: keep improving poieo
folder: ~/code/poieo
prompt: |
  Find one thing worth fixing, fix it, run the tests.
```

Point a daemon config at the folder, and every file in it becomes a flow:

```yaml
store: .poieo
binding: bindings/local.yaml
tasks: tasks/
```

Everything else is defaulted. It runs hourly (`every: 30m`, `every: loop`, or
`at: "0 3 * * *"` to change that), the model comes from the binding's default
role, the step gets the `files` and `shell` toolsets and 40 turns, and state
carries from one run into the next. `role`, `tools`, `max_turns`, `enabled`,
and `binding` are there when a task outgrows the defaults.

| command | does |
|---|---|
| `poieo tasks tasks/` | list the cards, with their schedules (a daemon config works too) |
| `poieo show tasks/keep-improving.yaml` | render the flow the task expands to |
| `poieo run tasks/keep-improving.yaml -b bindings/mock.yaml` | run it once |
| `poieo eject tasks/keep-improving.yaml` | write that flow out as a real graph; the task names it from then on |

The sugar is not a second configuration format: a task expands into exactly the
flow and graph you would have written by hand, `show` proves it, and `eject`
hands it over the moment one line stops being enough. An ejected graph still
reads `{{ input.journal }}`, which the task supplies -- run it through the task,
or pass `--set journal=...` when running that graph on its own.

A task's identity is its **filename**, so the title on the card can be
rewritten without orphaning its run history. Paths written inside a task file
resolve against the task file itself.

### What a task remembers

Each task keeps a journal -- `memory/shortterm/keep-improving.md`, named for the
card -- and reads it before every run. It sits with the rest of what the project
remembers, not among the cards: a card is a thing you edit, a journal is a thing
that grows every night, and side by side the folder of definitions went dirty in
git on every run.

```
- 2026-08-22 03:14 . did     fixed the flaky interval test on Windows
- 2026-08-22 08:02 . you     leave prose alone, spend the night on tests
- 2026-08-22 09:30 . did     added two cases to test_cron
```

poieo appends a `did` line after each run that finished (the model's own
closing sentence) and a `failed` line after one that did not. You add a `you`
line:

```bash
poieo note tasks/keep-improving.yaml "leave prose alone, spend the night on tests"
```

-- or by opening the file and typing one. The tail is read as text and never
parsed, so a line you wrote works exactly like a line poieo wrote. The file
keeps everything.

The journal reaches the prompt in two parts: everything that arrived since the
task last worked, in full, and then the tail of what came before, bounded. The
task's own last entry is the divide, so a note cannot be crowded out by history
however long the journal grows -- what is new is chosen by where it is, not by
how much of it there is.

This is what stops a standing task from re-doing last night's work, and it is
where the morning review's accept and discard notes will land once the review
screen ships.

### What a project remembers

The journal is short-term on purpose -- old lines age out of the prompt. The
long-term half lives beside the cards, and creating the folder is the whole
opt-in:

```
tasks/
  memory/
    constitution.md      one page, in front of every run of every task
    facts/batch-cap.md   one file per learned entry
```

The page is read whole, every run, first -- put the rules there that every
task must hold and that nothing would think to look up. The entries under
`facts/` are chosen per task: by a scope in their frontmatter (`global`, a
task's name, or a path), by the words they share with what the task is about,
and above all by naming the code the task is working on. A wrong entry is not
deleted; set `superseded_by:` and it steps aside, file and history intact.

Every run also leaves a full record under `.poieo/episodes/`, unclipped where
the run log clips, so an entry's `source:` can name the run that taught it --
anything the project claims to remember can be walked back to the work it
came from. Ask what a task will actually see, and why:

```bash
poieo memory tasks/                      # the page, the counts, the lookup
poieo memory tasks/keep-improving.yaml   # the exact block its next run gets
```

Entries can name each other. `[[name]]` in the prose means *these belong
near each other*, and whatever a chosen entry mentions arrives beside it --
even sharing no word with the task. Frontmatter carries the stronger claims:
`links: {depends_on: [...]}` for what an entry leans on (brought along, one
step, never further), and `links: {contradicts: [...]}` for a disagreement.
A disagreement is never resolved by a machine: `poieo memory` lists the
pair and a person settles it -- and once one side is set aside, whatever
leaned on it is flagged for a second look.

The project can also learn by itself. Every run already leaves a full
record; a learning pass reads the unread ones and proposes entries, which
poieo validates and writes with `source:` naming the runs that taught them
-- so anything learned overnight can still be walked back to the work it
came from. Run one by hand, or let the daemon do it while nothing else is
running:

```bash
poieo learn tasks/            # one pass, now
```

```yaml
learn: 1d                     # in the daemon config; needs its default binding
```

The pass keeps entries and sets entries aside; it never deletes, never
overwrites, and never touches the constitution -- that page stays yours.
The model that reads the night is the binding's `learner` role (unbound, it
falls through to the default), so pointing your best model at it is one
line. `.poieo/learning.jsonl` says what every pass did, and an empty pass
is a fine answer: most nights teach nothing.

Connections wear in with use. When two connected entries both did real work
in a run that succeeded -- their own words in what the run produced, not
merely having been shown -- the path between them wears a little, and later
retrievals carry it sooner and one step further. Wear fades on its own,
no entry's connections can hoard it, and it lives outside git in
`.poieo/strength.json`: delete the file and the project forgets which paths
were worn, relearns them by working, and loses not one word of meaning.

And the memory keeps itself honest. `poieo memory` flags what deserves a
second look -- an entry leaning on one that was set aside, an entry naming
code that is gone or that changed after the entry was written (edit the
entry after looking, and the flag clears) -- and the next pass is shown the
same doubts, free to retire an entry with its ordinary set-aside. Entries
set aside long enough, and named by nothing, move whole to `memory/attic/`:
out of every prompt and every count, restored by moving the file back,
deleted never. A pass may also *suggest* one line for the constitution;
poieo records and shows it, and only you ever edit that page.

Entries the project learns are sealed to the files they were written
about: the pass keeps the exact bytes under `.poieo/blobs/`, so a doubt
means the content really differs -- a merely-touched file raises nothing --
and the original an entry was written against is always there to open.
Keepsakes are copies, never meaning: one that nothing references anymore
is let go after the same grace the attic uses, and losing one costs a
precise comparison, not a word of what was learned.

Finally, the memory answers for itself. `poieo memory` reads the recent
run records and says how many runs actually used what they were shown, and
names any entry shown again and again without ever being used -- dead
weight for you to look at. It acts on none of it: numbers inform, people
and passes decide. (Measuring use by what the model truly attended to
needs a serving stack that can report attention; until then the judgment
is the same words-in-the-output test the wear system trusts.)

Nothing configures this. No `memory/` folder, no trace of the feature;
everything in it is markdown you edit and git versions. A worked pair of
cards sharing one memory lives in `examples/remembering/`.

### Tasks leaving each other notes

A task can write a line in another task's journal, using the same file and the
same shape you do:

```yaml
name: build the docs
folder: ~/src/thing
prompt: Rebuild the docs when the source has changed.
tools: [files, shell, notes]     # `notes` is opt-in
```

It then has one more tool, `tell`, and its prompt lists the tasks it may use it
on. The link checker sees the result on its next run:

```
New since you last worked:
- 2026-08-23 03:00 . task    [build-docs] rebuilt the docs; 30 links changed
- 2026-08-23 08:02 . you     ignore external links

What you did before that:
- 2026-08-22 03:14 . did     checked 12 links, all fine
```

A note is **news, not an instruction** -- the recipient is a model reading
text, and may ignore it exactly as it may ignore what you wrote. It carries a
line, not data: tasks that need to hand over real output share a folder, and
the note says there is something new there.

And a note **wakes nobody**. It is read on the recipient's next scheduled run,
which is why two tasks writing to each other still run only on their own
triggers and cannot spin each other up.

## The resident layer

```yaml
store: .poieo
binding: bindings/hybrid.yaml
flows:
  - name: triage
    graph: graphs/support-triage.yaml
    trigger: {type: interval, every: 30s}
    input: {message: "…"}

  - name: revision
    graph: graphs/draft-review.yaml
    trigger: {type: loop, cooldown: 10s}
    carry_state: true                  # each run starts where the last one ended
```

| trigger | fires |
|---|---|
| `interval` | every `every` (`30s`, `5m`, `2h`), on an absolute grid; a run that overruns skips missed ticks instead of queueing them |
| `cron` | on a 5-field expression, local time — `*/5`, ranges, lists, `mon-fri`, and the standard day-of-month **or** day-of-week rule |
| `loop` | back to back forever, pausing for `cooldown`; iterations never overlap |
| `manual` | only when something asks |

All four accept `max_iterations`. `input_file` re-reads the payload before each run, so an
external process can feed a flow. `on_error: stop` halts a flow after a failed run;
the default keeps it up.

Every graph, binding, and role is validated at startup — a typo in a flow that fires at 3am
fails at launch, not at 3am. `SIGINT`/`SIGTERM` drains in-flight runs and closes clients; a
second signal exits immediately.

```bash
poieo flows  examples/poieo.yaml     # what would run, on what trigger, against what model
poieo daemon examples/poieo.yaml     # stay up
poieo daemon examples/poieo.yaml --once --flow triage
```

While the daemon runs it serves a page on `http://127.0.0.1:8484` (`--port` to
change it, `--no-web` to turn it off). It ships built, so there is nothing to
install: open it to watch flows move, click one to read what it did turn by
turn, and take or throw away what it left you. The picker in the corner switches
skins; `ledger`, the plain one, is the default.

Everything the page reads is plain HTTP too. `GET /api/events` streams every run
event live (SSE), `/api/flows` and `/api/runs` answer what is running and what
already ran, and `/api/runs/<id>/diff` shows what one run changed. Only two
routes in the whole surface change anything, and they are the two below.

To work on the page itself: `npm run build --workspace web-ui` refreshes what the
daemon serves, `npm run dev --workspace web-ui` runs it on 5173 against a daemon
on 8484, and `npm test --workspace web-ui` is its suite.

## Work you look at in the morning

A flow that names a `workdir` does not work in your project. It works in a
private copy of it, and each run lands as one **change** carrying its own
one-line summary of what it did.

```yaml
flows:
  - name: chores
    graph: graphs/agent-task.yaml
    workdir: ../my-project      # where the work happens
```

Your project is never written to while you sleep. In the morning it is exactly
as you left it, and the night's work is waiting:

```bash
curl     127.0.0.1:8484/api/flows                     # how much is waiting
curl     127.0.0.1:8484/api/runs/<id>/diff            # what one run did
curl -X POST 127.0.0.1:8484/api/flows/chores/accept   # take it
curl -X POST 127.0.0.1:8484/api/flows/chores/discard  # throw it away
```

Accepting puts the work into your project. Discarding is recoverable -- nothing
is ever thrown away for good. A run that found nothing to do is not a failure
and leaves nothing to review, and a run that failed keeps its half-finished work
aside instead of mixing it in.

None of this is required. A flow with no `workdir` behaves exactly as it always
has, and a `workdir` that nothing tracks still runs -- `poieo flows` says up
front that its changes can't be reviewed or undone.

## Run logs

Every run appends a JSONL event stream under `<store>/runs/<run_id>.jsonl` plus a summary
line in `<store>/runs/index.jsonl`.

```bash
poieo runs list --store examples/.poieo
poieo runs show 20260820T130243-36ef0db5 --store examples/.poieo
```

Each `node_finished` event records which binding served it, the model that answered, the
branch a router took, and token usage — enough to answer "what ran, what did it decide,
what did it cost" without a database.

## Library use

The CLI is a thin shell over the library; the web editor planned next calls the same
functions.

```python
import asyncio
from poieo import load_graph, load_binding, execute, ProviderPool, RunStore

graph = load_graph("examples/graphs/support-triage.yaml")
binding = load_binding("examples/bindings/hybrid.yaml")

async def main():
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, RunStore(".poieo"),
                               input={"message": "the export button crashes"})
        print(result.status, result.path, result.outputs)

asyncio.run(main())
```

`execute` never raises for an in-run failure — the error lands on `result.error` so a daemon
flow can log it and stay up. Spec and binding problems still raise, since those mean the
flow is misconfigured rather than flaky.

## Layout

```
src/poieo/
  expr.py            sandboxed expressions + {{ }} templating
  graph.py           logical layer: nodes, wiring, validation
  task.py            the short form: one file expands into a flow + a graph
  binding.py         physical layer: providers, roles, param merging
  providers/         anthropic · openai_compatible · ollama · mock
  runtime/           context, node implementations, the graph walker
  daemon/            cron, triggers, flow config, the resident service
  store.py           append-only run log
  checkpoint.py      the only module that knows git exists
  web/               observation API, event fan-out, the built page
  cli.py             command line front end

web-ui/              the page's source: state, skins, review
  src/state/         events folded into one presentation-neutral model
  src/skins/         how that model is drawn; adding one is a module and a line
  src/review/        last night's work: the list, the diff, accept and discard
```

## Not built yet

* The web editor. The graph schema is the contract it will produce; `poieo show --mermaid`
  renders a graph today.
* Control from the page: pause, resume, run-now. The observation and review
  surfaces are built; nothing yet starts or stops a flow from the browser.
* Node types beyond `llm`, `router`, and `agent` (map/fan-out).
  `runtime/nodes.py` has a `NODE_TYPES` registry to add them to.

## Tests

```bash
pytest -q
```
