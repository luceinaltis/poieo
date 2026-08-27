# CLI

`src/poieo/cli.py`

A thin shell over the library — Typer for the argument parsing, and nothing
that only the CLI knows how to do. The web API calls the same functions.

## The commands

| command | does |
|---|---|
| `init` | write a working project into this folder, bound to what this machine has |
| `validate <graph\|card>` | preflight everything a run would need |
| `run <graph\|card>` | execute it once |
| `daemon [config]` | keep flows resident, and serve the page |
| `check` | probe every declared endpoint |
| `config` / `config models` | what this project is bound to, and what else it could name |
| `memory [card]` | what the project keeps, and what one card will be shown |
| `learn <tasks/>` | one learning pass, now |
| `runs list` / `runs show` | read the run log |

Nine more are registered `hidden=True` — `show`, `view`, `edit`, `flows`,
`tasks`, `note`, `eject`, `reset`, `version`. They are real and supported;
hidden keeps `--help` to the surface a new user needs. If you are adding a
command, ask which of the two lists it belongs on.

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

## `init` asks the machine; the CLI decides

`detect()` returns the engines that answered — see [storage.md](storage.md) —
and `init` is where the choosing happens, because choosing is a front end's job.
Unattended it takes the first engine and that engine's first model; every other
engine still lands in the binding for a role to name. `--mock` skips detection
entirely and is the only way `mock` ever becomes a project's default.

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
(`hf.co/empero-ai/…`) survives. That is the form `config use` will take back —
what a reader copies out has to be a thing they can type in.

**Known divergence:** `ResolvedModel.describe()` still renders `provider:model`,
so `poieo flows` and `poieo validate` spell it with a colon. Two spellings for
one thing is the tax [DESIGN.md](../DESIGN.md) principle 7 exists to refuse;
unifying them belongs with the write half.

## Cards and graphs are one argument

`validate`, `show`, `run` and `view` all take "a graph or a card".
`_load_card()` answers which (by document shape — see [tasks.md](tasks.md)) and
`_load_spec()` returns the graph either way: the file itself, the graph a card
names, or the graph a card expands to. Each is loaded **once per command** — `run`
used to read the same file four times through helpers that each opened it again.

A card run by hand and the same card run by the daemon must write **one**
history, not two, so `run` asks for the store from the *card's own folder* rather
than the cwd, and `layout_for()` answers with the project's `runs/` if the card
is in one. Both runners also call `task_payload()` for the journal and memory,
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
