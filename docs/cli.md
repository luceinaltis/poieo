# CLI

`src/poieo/cli.py`

A thin shell over the library — Typer for the argument parsing, and nothing
that only the CLI knows how to do. The web API calls the same functions.

## The commands

The front page is grouped by **what a person is trying to do**, not by which
layer of the design a command touches. `SETUP`/`BOARD`/`AFTER` in `cli.py` are
the panel titles, passed as `rich_help_panel`:

| panel | commands |
|---|---|
| **Setting up** | `init`, `validate`, `check`, `config` |
| **Your tasks** | `run`, `daemon`, `tasks`, `note`, `asking`, `answer` |
| **What happened** | `memory`, `learn`, `runs` |

Six more are registered `hidden=True` — `show`, `view`, `edit`, `eject`,
`reset`, `version`. They are real and supported; hidden keeps `--help` to the
surface a new user needs. If you are adding a command, ask which panel
it belongs in, or whether it belongs on the page at all.

`tasks` and `note` are on the page because this is a **task board**: someone who
cannot find how to list their tasks has not been shown the product. They were
hidden while `memory` and `learn` — both opt-in, both off unless a folder exists
— were visible, which had the surface exactly inverted.

### `asking` and `answer` are the only two that need poieo already running

Every other command reads files. These two ask the daemon, because a question a
[`confirm` node](graph.md) left is state that daemon is holding — and answering
it releases a `then:` inside that process, setting the rest of a chain going.

```
$ poieo asking
land  [land/hold]
    Merge #181? It changes a public interface.

answer one with: poieo answer <task> <choice>

$ poieo answer land land
land: land
```

They are clients of `POST /api/tasks/{project}/{task}/answer` and
`GET /api/tasks` — the board's own routes, so the terminal and the browser can
never disagree about what is being asked. `--port` names the board when it is
not on 8484, and no daemon answering is a sentence saying to start one rather
than a connection error.

## The front page speaks the user's three words

[DESIGN.md](../DESIGN.md) principle 7: the vocabulary is a **task**, a **run**,
a **change**. Worktrees, bindings, providers and schedulers are machinery, and
machinery does not appear in the interface — least of all on the first screen
somebody ever sees. The help used to read:

```
daemon    Start the resident scheduler and keep flows running.
check     Probe every provider declared in a binding.
validate  Parse a graph or task (and optionally a binding) and report problems.
```

Three lines, six machinery words, and a newcomer none the wiser. A test asserts
that `scheduler`, `provider`, `binding` and `worktree` appear nowhere in
`poieo --help`, and that `task` — the word that replaced them — is there. The
panel titles and short help are written against it.

## `poieo daemon` takes as many projects as you name

`poieo daemon` with no argument is the project you are standing in, which is
what it has always been. With arguments it is those projects, one board over all
of them: `poieo daemon . ../notes`. Each argument is read on its own — a marker
file, a folder holding one, or a folder of cards — so the spellings that worked
for one still work for each.

`--task` is narrowed across everything named, and refuses while listing every
project it looked in. Which project a task lives in is not something the user
should have to say in order to name it.

The same rule reaches past the help. `humanize()` in `daemon/triggers.py` renders
an interval in the units somebody would have written it in — `every 30m`, not
`every 1800s`. That string is what `tasks` and `validate` print, what the board
labels a task with, and the reason every interval run records for having fired,
so one readable spelling covers all of them.

## Every command fails in the product's voice

`@_guarded` wraps each command, catches `PoieoError` and prints
`error: <message>` in red with exit code 1 — never a traceback. It is applied at
registration rather than inside each function, because the daemon command once
printed a traceback when a single site forgot its `try/except`; making the guard
part of registration removes the category.

## Discovery: the flag always wins

Inside a project, commands need no flags — but **discovery only fills silence**,
and what filled it is echoed.

```
_find_binding()   the --binding flag  →  the card's own `binding:`  →  the project's
_project_file()   the named config    →  the nearest poieo.yaml (else a refusal)
_resolve_store()  the --store flag    →  the project's runs/
```

*Automatic is fine, invisible is not*: `run` prints `binding <path> (from
<poieo.yaml>)` whenever the project filled it in. The refusal for "no project
here" is written once, in `_project_file()`, because a sentence the user reads is
a thing with one wording and two copies are two chances for that to stop being
true. `nothing_found()` in `project.py` is the same rule for `init`'s refusal.

Anything on the front page has to work when typed **bare**, since that is how it
will be typed first: `tasks`, `daemon`, `memory` and `config` all fall through
to the project's own answer. `poieo tasks` used to require a folder,
which is a poor greeting from a command whose whole job is "show me my board".

## `init` asks the machine; the CLI decides

`detect()` returns the engines that answered — see [storage.md](storage.md) —
and `init` is where the choosing happens, because choosing is a front end's job.
Unattended it takes the first engine and that engine's first model; every other
engine still lands in the binding for a role to name. `--mock` skips detection
entirely and is the only way `mock` ever becomes a project's default. `--name`
says what a board should call the project; unattended it is the folder's name,
written into the marker rather than left to be inferred.

Existing files are never touched, so `--name` against a folder that already has
a `poieo.yaml` cannot land — and says so, naming the line to add. A flag that
quietly did nothing is worse than one that refuses.

The library half is deliberately question-free: `binding_document()` renders a
binding for engines the caller has already settled on, and `init_project()`
writes files for a binding body it is handed. Nothing under `cli.py` prompts,
which is what keeps the same functions usable from the web board.

## `poieo config`

`init` happens once; models change every month. `config` is where a project's
binding is read after that — and, once the write half lands, changed.

| | |
|---|---|
| `poieo config` | the binding, its endpoints, its default and its roles. **Reads files, opens no socket.** |
| `poieo config models` | what each declared endpoint serves **right now**, marked with what is already spoken for |
| `poieo config use <provider/model>` | point the default — or `--role NAME` — at a different model |
| `poieo config add` | look at the machine again, and declare any engine not already here |

Bare `poieo config` reports instead of printing help (`invoke_without_command`),
because "what am I bound to" is the question people arrive with and making them
find a subcommand to ask it is a tax. The subcommands are for changing the answer.

Three neighbouring questions stay apart, because they are easy to confuse:
`check` asks whether an endpoint is **up**, `config` reads what the **file**
decided, and `config models` asks the endpoints for their **catalogue**. Only
the last two are new; `check` keeps its place at the top level, where README and
`AGENTS.md` already send people.

`config models` asks every provider at once. Two endpoints asked in single file
is two timeouts on a laptop where neither is running, and this is a command read
one screen at a time. It reaches `detect.models_for()` — the same function
detection uses, keyed by provider type — so a binding and the board can never
disagree about where to look for a provider's models. A type that cannot be
asked at all (`mock`, or a backend a caller registered) says so rather than
reading as unreachable; `detect.askable()` is that distinction.

Models are written `provider/model`, splitting once, so an id full of slashes
(`hf.co/empero-ai/…`) survives. That is the form `config use` takes back — what
a reader copies out has to be a thing they can type in, and a test asserts the
round trip.

`ResolvedModel.ref` is the **one** place that spelling is built. Four sites used
to assemble it themselves and one of them used a colon, so the roster and
`poieo validate` disagreed with `poieo config` about what a model is called.
`describe()` is now `f"{role} -> {ref}"`.

## `config use` edits, and undoes itself if it was wrong

A binding is a file somebody keeps: the generated one carries its model
catalogue in comments, a hand-kept one carries whatever its owner put there.
Loading it with a YAML parser and dumping it back would take all of that, so
`rebind.py` does **text surgery** — it rewrites the two lines it came for and
leaves every other byte alone.

Surgery is fragile, and the module is written expecting to be wrong sometimes:

- it **refuses before writing** when it cannot find what it came to change,
  naming the file and the key so a person can do it by hand. Flow-style YAML
  (`default: {provider: x, model: y}`) is legal, rare, and exactly where
  guessing corrupts a config;
- and it **verifies by reloading** — a result that will not parse, or that does
  not resolve the way it was asked to, is restored and raised.

`config use` adds two refusals of its own before any of that: a provider the
binding does not declare, and a model the endpoint says it does not serve. The
second is the typo the whole `config` pair exists to prevent — a model named
from memory does not fail here, it fails at 3am in a run. It is **best effort**:
an endpoint that does not answer is not a verdict, so the edit proceeds and the
command says it could not check.

## `config add`, and the line between declaring and choosing

Detection otherwise runs **once**, at `init`. Install Ollama next week and the
binding has never heard of it. `config add` takes the same look `init` took and
declares whatever is not already in `providers:`.

It **only adds**, and the boundary is the point:

- an endpoint already declared is left exactly as it is, because somebody may
  have pointed it at another port or another machine, and `add` is not a second
  `init`;
- and `default:` never moves, because declaring a model and choosing one are
  different decisions. `add` widens the pool; `use` picks from it.

An engine with no address is declared without one — Claude's SDK knows where it
lives, and a guessed `base_url` is worse than none.

## Cards and graphs are one argument

`validate`, `show`, `run` and `view` all take "a graph or a card".
`_load_card()` answers which (by document shape — see [tasks.md](tasks.md)) and
`_load_spec()` returns the graph either way: the file itself, the graph a card
names, or the graph a card expands to. Each is loaded **once per command** — `run`
used to read the same file four times through helpers that each opened it again.

A card run by hand and the same card run by the daemon must write **one**
history, not two, so `run` asks for the store from the *card's own folder* rather
than the cwd, and `layout_for()` answers with the project's `runs/` if the card
is in one. Both runners also call `card_payload()` for the journal and memory,
and `record_run()` afterwards — the journal contract in [tasks.md](tasks.md)
requires every runner to land there.

## `eject`

Writes out the graph a card stands for, then rewrites the card to name it. The
graph is dumped with `exclude_defaults=True`, so what lands on disk is what the
card actually said rather than every field with its default spelled out.

The card keeps only what still means something once a graph exists — name,
folder, schedule, binding, `enabled` — and the command says two things out loud:
that comments in the card were not preserved, and that the ejected graph still
reads `{{ input.journal }}`, which only a card supplies. Run it through the card,
or pass `--set journal=…`.

`eject` is the escape hatch that keeps the short form honest: the moment one line
stops being enough, the sugar hands over a real graph and gets out of the way.

## `view` and `edit`

`viewer.py` renders a graph as a self-contained HTML page (`poieo view`), and
`poieo show --mermaid` emits just the flowchart. `editor.py` is a drag-and-drop
canvas over the same schema (`poieo edit`).

The editor owns only the **logical** layer — nodes, wiring, prompts, conditions,
and which role each node calls. It never edits a binding; which model runs a role
stays a separate file, which is the whole point of the split. Node positions
round-trip through the optional `ui:` block, which the runtime ignores.

Saving needs somewhere to put the file, and there are two adapters: `jupyter`
(PUT through a running Jupyter server's contents API, useful where the only
reachable port already belongs to Jupyter) and `none` (download and copy
buttons). Folding this into the board is open work — see [web.md](web.md).

## Library use

The CLI adds nothing the library cannot do:

```python
from poieo import load_graph, load_binding, execute, ProviderPool, RunStore

async with ProviderPool(binding) as pool:
    result = await execute(graph, binding, pool, RunStore("runs"), input={...})
```

`execute` never raises for an in-run failure — see [runtime.md](runtime.md).
