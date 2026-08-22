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
junior contributor loose in. `poieo run examples/graphs/agent-task.yaml -b
examples/bindings/mock.yaml --set workdir=/tmp/demo` exercises the loop
offline.

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
