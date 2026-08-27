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
store: runs              # where a run's events and result go
binding: models/local.yaml
tasks: tasks/            # where the jobs are; one file each
learn: 1d
```

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
  memory/shortterm/   memory/longterm/   what a person reads and edits (git)
  memory/cache/                          derived; delete and lose nothing
  runs/                                  what happened — `store:` moves this
    index.jsonl · events/ · results/
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
- one summary line in `runs/index.jsonl` — what ran, its status, path, usage and
  `change`

That is enough to answer *what ran, what did it decide, what did it cost* without
a database. `runs/results/<run_id>.json` is the third file, written by
[memory](memory.md) — the same run's full outcome, unclipped.

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
`models/default.yaml` and `models/mock.yaml`, a sample card, an empty
`constitution.md`, `AGENTS.md`/`CLAUDE.md` for whoever works in the project,
and `.gitignore` entries for `memory/cache/`, `runs/` and `worktrees/`.

The empty page is written so the memory is a folder you can see rather than a
feature you have to be told about — and nothing switches on, since the page is
comments and comments are stripped before any prompt.

Existing files are never touched (they are reported as `kept`), so `init` in a
full project changes nothing. It finishes by loading the project it just wrote —
tasks and cards included — because a generated project that cannot load is an
init bug, and it should be caught there rather than at 3am. That single call is
the only reason `project.py` knows the daemon exists.

## Detection

`detect.py` looks at the machine **once**, at `init`, and asks every address it
knows: Ollama, LM Studio, vLLM/SGLang and llama.cpp on their usual ports, and
the Claude SDK, which resolves an `ANTHROPIC_API_KEY`, an auth token or an
`ant auth login` profile by itself. All of them at once, 1.5s each, because the
common case is a machine where most of them are not listening.

It **asks, and never decides**: it returns the engines that answered and the
models each reported, and touching a file is the caller's business. Detection
never runs again — **run time reads files, nothing else.** A binding names an
endpoint because somebody wrote it there, not because a port answered tonight.

The order in `CANDIDATES` is the order a picker shows, and the order an
unattended `init` takes its answer from. **Local servers lead**, for
[DESIGN.md](../DESIGN.md) principle 3's own reason: a resident that runs around
the clock has to be able to do it without anybody watching the token spend, so
the metered endpoint is not what a project falls into by default. A machine with
both a Claude credential and an answering Ollama declares both and binds the
Ollama. Moving that is `poieo config use`, one command.

`models_for(type, base_url)` is the one place that knows how each backend lists
what it has — `/api/tags` for Ollama, `/models` for anything OpenAI-shaped, the
SDK for Claude. Keyed by **provider type** rather than by address, because the
question outlives detection: a binding declares a type and a base_url, and
`poieo config models` asks from there. Two copies of that knowledge would
eventually look in two places. `askable(type)` says whether the question can be
put at all — `mock` answers from the binding file itself, and so does a backend
somebody registered through `providers.register()`.

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
