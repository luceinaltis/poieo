# Storage — where everything lives, and the run log

`src/poieo/layout.py`, `src/poieo/project.py`, `src/poieo/detect.py`,
`src/poieo/store.py`

Files are the sole source of truth. There is no database of record; at most a
derived index under `memory/cache/`, rebuilt from the files at any time and safe
to delete.

## A project is a folder with a marker

**A project is the folder holding a `poieo.yaml`. Without one, the folder you
pointed at stands in.** `find_project_file()` walks upward for the marker the way
git finds `.git`.

`poieo.yaml` is deliberately shallow — it declares *where things are*, not what
they contain:

```yaml
name: night shift        # what a board calls this; optional
store: runs              # where a run's events and result go
binding: models/local.yaml
tasks: tasks/            # where the jobs are; one file each
learn: 1d
```

`name:` is the one key that says nothing about where anything is, and it is
optional because the folder name answers for it nearly always -- `display_name`
falls back to the folder, and to the folder again if the key is blank. It earns
its place in the one case the folder cannot cover: a worktree is a second folder
with the *same* name as the first, so two daemons on two ports serve two boards
that are otherwise indistinguishable.

`poieo init` writes the key, filled in with the folder's name, and `--name`
sets it instead. The folder is a good guess and a bad default: written into the
file it is a starting point a reader can see and change, where left as a
fallback it is a rule they have to be told about. The fallback stays for the
markers people write by hand, which are most of them.

There is no list of jobs here. `flows:` was one, and a marker that still carries
it is refused by name rather than by "not a setting here" -- a list in a shared
file is the worse of the two for a board that creates jobs, for a diff that
should be about the job that changed, and for a reader who had to learn two
spellings of every key.

`ProjectSpec` is what commands read to fill flags the user left silent; the
**flag always wins, and discovery only fills silence**. `DaemonConfig` extends it
when something actually intends to run the tasks. One schema, read to the depth
the caller needs.

Paths inside `poieo.yaml` resolve against the config file, never the cwd
(`resolve_path()`), so standing somewhere else cannot change where a run's
history lands.

## Layout — one answer to "what lives where"

`layout.py` exists because `.poieo` used to appear as a literal in seven modules,
each assembling its own idea of where a project begins — and they had already
drifted. Three answers to one question is two too many.

```
<root>/
  memory/shortterm/                      one journal per card (git)
  memory/longterm.sqlite3                the long memory itself — one per project
  memory/cache/                          derived; delete and lose nothing
  runs/                                  what happened — `store:` moves this
    index.jsonl · events/ · results/ · asking/
  worktrees/                             each task's private checkout
```

Two rules that are easy to get wrong:

- **`store:` moves the run history and only that.** The memory stays with the
  project, and so do the working copies. A copy of a repository is not a run log,
  however much it is written during one.
- **`store:` counts only when the document actually named it.** `Layout` takes a
  `runs_override` set from `"store" in model_fields_set` — a default that happens
  to match is not a decision, and treating it as one would make every silent
  project look like it had asked for something.

**Nothing in `layout.py` touches the disk.** Asking where a thing would live is
not the same as making it; the callers that write are the ones that create.

`layout_for(start)` finds the nearest marker and *parses* it, because `store:` is
part of the answer — a caller that knew the root but not that key would write a
run's events and its result to two different folders.

## The run log

`store.py` is append-only. Every run writes:

- `runs/events/<run_id>.jsonl` — one JSON line per event
- one summary line in `runs/index.jsonl` — what ran, **whose project it was**,
  its status, path, usage and `change`

That is enough to answer *what ran, what did it decide, what did it cost* without
a database.

`project` is on the record because one daemon can run several, and then "which
task ran" no longer says whose night it was. It is written where the daemon
knows it and read where the board needs it: the runtime carries it as a label
and never looks at it, the same way it carries `task`. It is on the
`run_started` frame too — the board learns what is happening from the stream,
not from the index. `runs/results/<run_id>.json` is the third file, written by
[memory](memory.md) — the same run's full outcome, unclipped.

`runs/asking/<card>.json` is the fourth, and the only one that is deleted
rather than accumulated: the run a [`confirm` node](graph.md) parked, kept
whole so that the answer can still fire the card's `then:` after a restart, and
removed the moment somebody answers. One per card, because only the newest
question stands.

**A record is written once, with one exception.** `write_result` refuses to
overwrite — one run, one record — except when an answer arrives for a run that
ended by asking. Without that exception the record would read `asking` for
good: a run that never finished, about a decision somebody made.

### Durability

Events settle for the OS cache; **only the index line is fsynced**. Events arrive
one per model turn and per tool call, from coroutines on the loop the daemon
shares with the web server, and an fsync there is milliseconds of everything
standing still. Durability is bought once per run, on the file that answers "what
ran".

Writes take a lock, so concurrent tasks in one process are safe.

### Reading

The index grows for the daemon's lifetime and the web UI asks per request, so
reads walk **backwards from EOF** in fixed-size blocks (`_lines_backwards`) and
parse only until enough rows have matched. A month of uptime would otherwise
cost half a second per call. Splitting happens on bytes and a line is decoded
only once whole, so multi-byte text spanning a block boundary is safe.

`summary(run_id)` pre-filters on the raw line before parsing, and returns the first
hit — newest first, because a run may be re-recorded.

`json_records()` is the one reading rule for every JSONL file poieo writes: skip
blank lines, skip anything that will not parse, skip anything that is not a
mapping. These are plain files a long-lived daemon appends to and a user may
open, so a blank line or a half-written last one is a thing that happens, and
neither is worth refusing to answer over.

`NullStore` (`poieo run --no-log`, and tests) is empty on **both** sides.
Dropping the writes but inheriting the reads would leave it answering from
whatever `runs/` a folder happens to hold, which is somebody else's history
rather than none.

## `poieo init`

Writes a working project into ordinary files: `poieo.yaml`,
`models/default.yaml` and `models/mock.yaml`, a sample card, a memory whose
page is empty, `AGENTS.md`/`CLAUDE.md` for whoever works in the project,
and `.gitignore` entries for `memory/cache/`, `runs/` and `worktrees/`.

The empty page is written so the memory is something you can open rather than a
feature you have to be told about — and nothing switches on, since the page is
comments and comments are stripped before any prompt.

Existing files are never touched (they are reported as `kept`), so `init` in a
full project changes nothing. It finishes by loading the project it just wrote —
tasks and cards included — because a generated project that cannot load is an
init bug, and it should be caught there rather than at 3am. That single call is
the only reason `project.py` knows the daemon exists.

## Detection

`detect.py` looks at the machine at `init`, and asks every address it
knows: Ollama, LM Studio, vLLM/SGLang and llama.cpp on their usual ports, and
the Claude SDK, which resolves an `ANTHROPIC_API_KEY`, an auth token or an
`ant auth login` profile by itself. All of them at once, 1.5s each, because the
common case is a machine where most of them are not listening.

It **asks, and never decides**: it returns the engines that answered and the
models each reported, and touching a file is the caller's business. **Run time
reads files, nothing else** — a binding names an endpoint because somebody wrote
it there, not because a port answered tonight.

Detection does run again in one place, and the boundary is worth stating: the
board's models panel asks on every paint, to notice an engine installed since
`init` that the project's binding has never heard of (see [web.md](web.md)). It
still only asks. Nothing is written until somebody presses the offer, and no run
is ever routed by what a port said tonight. `probe(candidates)` takes the subset
to look at, so the panel skips the addresses the project already declares — and
it is a request of its own, because a candidate nothing is listening on costs a
whole `HTTP_TIMEOUT` rather than refusing fast, which was measured after being
assumed the other way.

The order in `CANDIDATES` is the order a picker shows, and the order an
unattended `init` takes its answer from. **Local servers lead**, for
[DESIGN.md](../DESIGN.md) principle 3's own reason: a resident that runs around
the clock has to be able to do it without anybody watching the token spend, so
the metered endpoint is not what a project falls into by default. A machine with
both a Claude credential and an answering Ollama declares both and binds the
Ollama. Moving that is `poieo config use`, one command.

`catalogue_for(type, base_url)` is the one place that knows how each backend
lists what it has — `/api/tags` for Ollama, `/models` for anything OpenAI-shaped,
the SDK for Claude. Keyed by **provider type** rather than by address, because
the question outlives detection: a binding declares a type and a base_url, and
`poieo config models` and the board ask from there. Two copies of that knowledge
would eventually look in two places. `models_for()` is that answer read for its
ids, so there is still one request and one place that knows where to send it.
`askable(type)` says whether the question can be put at all — `mock` answers from
the binding file itself, and so does a backend somebody registered through
`providers.register()`.

### Whose machine

Two questions that look like one, and were one. `lists_installed(type)` says a
listing is things **pulled and ready** rather than a menu — a property of the
backend, as true of an Ollama on an office server as of one here.
`is_here(base_url)` says whether that machine is **this** one, which only the
address can answer: `localhost`, `::1`, and the whole `127.` net. It returns
None where there is no address, because Claude's SDK resolves its own and
calling that "somewhere else" would be a claim about a machine nobody named.

Reading the first as both had every Ollama anywhere telling the board it was on
this laptop. `where(base_url)` is `host:port` — the part of an address that
names a machine, and the only part [web.md](web.md) lets through.

Deliberately no further than string comparison. Resolving a hostname would turn
a question about a config into a DNS lookup, and being wrong costs a label,
never a request going somewhere it should not.

### An address nobody guessed

`CANDIDATES` is four ports on this machine, which is the right guess for a
laptop and no guess at all for the vLLM on 8001, the Ollama on a desktop or the
box in an office. `ask(base_url)` is those: it takes an address and finds out
what is there.

**It asks rather than being told.** Both listing shapes are tried against the
address, and whichever answers says which backend it is — so a caller supplies
an address and nothing else, instead of a form asking somebody to classify their
own server. `/v1` is tried as well: `http://box:8001` is what a person reads off
a terminal, the OpenAI shape lives one segment further down, and refusing the
address they have would be making them debug a URL to answer a question this can
answer itself.

`ask` is also the first place detection is handed a string somebody **typed**,
and a typed address has typos in it. `httpx` refuses a malformed one by raising
— `InvalidURL` for a port that is not a number, idna's own `UnicodeError` for a
hostname it cannot encode — and neither is a `RequestError`, so both went
straight past the clause that was catching. `_listed` catches all three now,
because "every outcome is a return value" is this module's rule and a caller
being shown a list has no use for a traceback. (This is detection's promise and
not the whole product's: a *declared* endpoint with a malformed `base_url` still
raises out of `providers.local` when something goes to run it, and `poieo check`
is where that surfaces.)

Silence is the right answer *inside* detection and the wrong one at the surface:
"nothing usable answered at `http://box:80O1`" is true, and has the reader
checking whether their server is up. So `unaskable(address)` says why an address
cannot be asked anything, and the two callers that take a typed one —
`poieo config add <url>` and `POST …/models/add` — ask it before they probe.
**Its shape and nothing else**: whether anything is listening is what asking is
for, and a check that guessed at reachability would refuse the office box on a
night it happened to be off.

The name comes from what the server said it was, and from the **host** when it
said nothing. `gpu-box` is something the person who typed the address will
recognise; `openai_compatible` would tell them nothing, being five products at
once. Nothing answering is None, and so is an empty listing — the rule
:func:`probe` holds, for the same reason.

`Engine.api_key_env` carries the **name** of a variable, and `rebind.declare`
writes it. Never a value: detection has no business holding a credential, and
the file this ends up in is one people commit.

### The endpoints that answer nothing until asked properly

An endpoint that wants a key answers **401 to a listing**, and a 401 is a
`Catalogue()` — which reads, all the way up, as "nothing usable answered". That
is a vLLM or SGLang started with `--api-key`, and every hosted endpoint reached
the way `config add <url>` reaches one: as `openai_compatible` with its address
written down. Asking without the key made those the one kind a key could not
add.

(The 14 named preset types in `providers/presets.py` — `openai`, `groq`,
`together` — are a separate gap and not this one. `askable()` does not know
them, so `catalogue_for` returns empty before it reaches a socket, and a binding
declaring one still reads as "nothing to ask". Adding a key changes nothing
there.)

So `catalogue_for` takes `api_key_env` and sends `Authorization: Bearer` when
that variable is set, and every caller holding a `ProviderSpec` passes
`spec.api_key_env` — `poieo config models`, `config use`'s check that a model is
really there, and both of the board's model routes. `ask(url, key_env)` carries
it through all three of its attempts and writes it onto the `Engine` it returns,
so a caller cannot end up having probed one endpoint and declared another.

Read straight from the environment, **not** through `providers.credential_for`,
which raises when the variable is unset. Detection asks and never decides: a
name with nothing behind it is a question for whoever typed it, and it is the
callers that took the name — `poieo config add` and `POST …/models/add` — that
say so. On the way *out* and never as a precondition: an endpoint that lists
for anyone still declares, because the key routinely lives in the environment a
wrapper starts the daemon under rather than the shell running the command, and
writing its name into a file people commit is a whole reason to be there. But
when the address answered nothing and the variable was empty, both are said,
since "nothing usable answered at …" alone is a true sentence about the wrong
problem.

### Who is actually answering

`openai_compatible` is four products in a trench coat: vLLM, SGLang, LM Studio,
llama.cpp and every hosted router speak it. `label_for()` answers *which*, from
three sources, and the order is the whole point.

**First, what the server said about itself.** `Catalogue.server` carries the name
found in `owned_by` on the listing's own entries. That field means "who owns the
model" in the OpenAI schema — OpenAI's own API answers `openai` and `system` with
it — so only values a server is *known* to write for itself are read as one, and
`_SAYS_ITS_NAME` is that short list. Each was verified in the server's source
rather than guessed:

| server | `owned_by` | where it is set |
|---|---|---|
| vLLM | `vllm` | `vllm/entrypoints/openai/engine/protocol.py` |
| SGLang | `sglang` | `python/sglang/srt/entrypoints/openai/protocol.py` |
| llama.cpp | `llamacpp` | `tools/server/server-context.cpp` |

**This is what tells vLLM from SGLang.** They share a default port and answer
listings of the same shape, so no amount of looking at the address ever could —
and it keeps working for a server moved onto a port nobody wrote down.

**Second, the address**, for `CANDIDATES`' own entries plus a very short list of
hosted endpoints worth naming. Right for a server that names itself nothing, and
deliberately short: a registry of every hosted endpoint is a table that goes
stale, and naming one wrongly is worse than not naming it.

**Third, nothing** — the caller falls back to the bare type.

A name **typed into the binding** is not among them, and that is the point. It
says what its author believed when they wrote it; the whole reason to ask an
endpoint anything is to find out what is really there. The board shows what
answered first and the author's key second (see [web.md](web.md)).

`probe()` keeps what a server said on the `Engine` it returns (`said`), and
`Engine.known_as` is `label_for` applied to it, falling back to the candidate's
own label. **Everything that puts a detected engine on a screen goes through
that one property** — `init`, `config add`, and the board's offer — so the
terminal and the browser cannot name one server two different things. Without
it they printed `vLLM / SGLang`, the pair the address can name, after having
just been told which of the two it was.

**Every engine found is declared**, not only the one that ends up serving
`default:`. A role exists so a graph can send its cheap step somewhere cheap,
and that is unreachable if the file names a single endpoint — so the pool is
written down once and picking from it later is an edit, not another round of
detection. `binding_document()` renders it, and the models each engine reported
land as a **comment**: they are a snapshot, and a list presented as fact would
go stale the first time a model was pulled.

Two things are deliberately not offered:

- **`mock` is never detected.** It answers from a script, so a project that
  fell back to it would run all night and produce invented text. It is always
  written as `models/mock.yaml` — `-b models/mock.yaml` exercises the wiring
  for free — but reaching for it stays deliberate, and `poieo init --mock` is
  the one way to make it a project's default.
- **An engine with no models installed.** Naming it would write a binding that
  fails on the project's first run.

When nothing answers, `init` refuses and writes nothing at all, naming every
address it tried. A half-written project, or one quietly bound to a script, is
worse than an empty folder.
