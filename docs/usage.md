# Using poieo

poieo keeps tasks running on models you choose and brings their changes back
for review. A task is a YAML file with a name, a folder, and instructions. This
guide starts with an offline mock run, then adds the parts needed for unattended
work.

Run `poieo --help` or `poieo <command> --help` for the complete command and
option reference. The component guides in [the documentation index](README.md)
describe the contracts behind each feature.

## Install

poieo requires Python 3.10 or newer.

```bash
git clone https://github.com/luceinaltis/poieo
cd poieo
pip install .
```

For an editable development install, use `pip install -e .` instead.

## Start a project

Create a folder for the board and initialize it with the scripted mock model.
The mock needs no network access or credentials.

```bash
mkdir my-board
cd my-board
poieo init --mock
```

Initialization writes:

- `poieo.yaml`, the project marker and default paths;
- `models/`, where model endpoints and role bindings are declared;
- `tasks/`, where tasks and their graphs live;
- `memory/`, where task journals and optional long-term memory live;
- `AGENTS.md`, a short operating guide for an agent working in the project.

It also creates gitignored `runs/` and `worktrees/` locations as they are
needed. Running `poieo init` again does not overwrite existing files.

To detect real local model servers and supported cloud credentials instead,
run `poieo init` without `--mock`. It records the endpoints and environment
variable names that answered; it never writes a secret value.

## Create and run a task

Create `tasks/keep-green.yaml`:

```yaml
name: keep the tests green
folder: ../the-project
prompt: |
  Run the tests. If one fails, find out why and fix it.
```

Relative paths are resolved from the task file. A prompt-shaped task needs a
real folder because its model receives file and shell tools there. With no
schedule written, the daemon runs it at startup and then every hour. Its state
and journal carry into later runs.

Check the task before letting it run unattended:

```bash
poieo validate tasks/keep-green.yaml
poieo show tasks/keep-green.yaml
poieo run tasks/keep-green.yaml -b models/mock.yaml
```

`validate` checks the task, graph, binding, paths, and templates. `show` prints
the graph the short task expands into. `run` performs one run and records it;
the explicit mock binding keeps this first pass offline.

Use `poieo tasks` to list the project’s tasks, schedules, and latest journal
entries. It also warns when a folder is not a Git repository and its changes
therefore cannot be reviewed or undone by poieo.

## Keep tasks running

Start the resident process from the project folder:

```bash
poieo daemon
```

The board opens at <http://127.0.0.1:8484>. It shows tasks, runs, questions,
model choices, and changes waiting for review. An ordinary task card can be
created, renamed, edited, switched on or off, and set aside in the browser.
Schedules, isolation, and graph wiring remain file-based settings.

The daemon rereads the tasks folder. Switching only `enabled` takes effect
without restarting it. Restart after changing other loaded task settings such
as a schedule, folder, binding, isolation policy, or graph relationship. A
prompt or graph file is read again when a new run begins.

Useful variants are:

```bash
poieo daemon --once             # run every task once, then stop
poieo daemon --task keep-green  # keep only one named task running
poieo daemon --no-web           # run without the browser board
poieo daemon poieo.yaml another/poieo.yaml # serve both projects
```

Keep the default localhost binding unless the network is trusted. A board
bound to another interface has no account or password layer.

## Review a change

When a task points at a Git repository, poieo works in a private copy. A run
can leave one change for you to inspect on the board. Accepting merges the
run’s commits into your current branch and refuses a checkout with tracked
edits. Discarding parks the old tip under a recoverable Git ref before resetting
the task’s private branch.

You can inspect recorded runs from the terminal too:

```bash
poieo runs list
poieo runs show <run-id>
```

If a task works in a folder that is not a Git repository, its edits happen in
that folder directly. There is no diff to accept and no automatic undo; the
task list warns about this before the run.

## Schedule and control work

The short schedule forms cover the common cases. Choose `every` or `at` for a
task; they are alternatives:

```yaml
every: 30m                  # duration, or the word "loop"
```

```yaml
at: "0 2 * * *"            # cron expression
```

`enabled: false` keeps either task present without running it.

Use a full trigger block when jitter, startup behavior, a cooldown, or a run
limit matters:

```yaml
trigger:
  type: interval
  every: 2h
  jitter: 10m
  run_at_start: false
  max_iterations: 5
```

The board can pause and resume a running task, or request an immediate run.
Pause stops future work at a safe boundary; it does not kill a model or shell
command in the middle of an operation.

A graph can stop at a `confirm` node and ask you to choose before downstream
work continues. Answer on the board, or from another terminal:

```bash
poieo asking
poieo answer <task> <choice>
```

The daemon must still be running because it owns the waiting question.

## Choose models

Run these from a poieo project:

```bash
poieo config
poieo config models
poieo check
poieo config add
poieo config use <provider>/<model>
poieo config use <provider>/<model> --role reviewer
```

`config` shows the current binding. `config models` asks declared endpoints
what they serve. `check` probes the binding. `config add` detects endpoints
installed since initialization, and `config use` changes the default or one
named role while preserving the rest of the YAML file.

A binding separates logical roles from physical providers:

```yaml
name: default
version: 1

providers:
  local:
    type: ollama
    base_url: http://127.0.0.1:11434

default:
  provider: local
  model: qwen3

roles:
  reviewer:
    provider: local
    model: qwen3
```

Hosted providers name a credential with `api_key_env`; put the value in that
environment variable, never in the YAML. Provider-specific headers, query
parameters, timeouts, retries, model parameters, context limits, and prices
are available when needed. See [bindings and model providers](binding.md) for
the schema and credential boundary.

## Isolate model tools

By default, file and shell tools run on the host inside the task folder. A task
can instead keep their effects inside a Docker environment:

```yaml
name: inspect dependencies
folder: ../the-project
prompt: Check the dependency tree and report risky upgrades.
isolation:
  image: python:3.12-slim
  network: none
```

Validate the task while Docker is available, then try it once before relying
on it. `poieo reset tasks/<task>.yaml` throws away that task’s reusable
environment without touching its project files.

Isolation is a boundary for commands, not a promise that Docker is a perfect
sandbox. The project folder is the task’s intended working surface; configure
network access and any extra mounts narrowly. Details and platform limits are
in [tools and isolation](tools.md).

## Journals and project memory

Each task has an append-only journal under `memory/shortterm/`. The next run
sees recent entries, including the result of the previous run. Leave a direct
instruction with:

```bash
poieo note tasks/keep-green.yaml "focus on the failing tests; leave prose alone"
```

Projects initialized by poieo also keep long-term memory in
`memory/longterm.sqlite3`. That database is the source of truth for the shared
page, learned entries, and their revision history. Read its status or preview
what one task will receive:

```bash
poieo memory
poieo memory tasks/keep-green.yaml
poieo learn
```

`learn` reads new run records with the binding’s `learner` role and retains
only lessons meant to stay true across tasks. Most runs should add nothing.
The browser can search, edit, and set aside learned entries. See
[project memory](memory.md) for budgets, recovery, and durability rules.

## Grow a task into a graph

A short task expands to one agent node. When the work needs several steps,
branching, commands, or a human decision, export that generated graph:

```bash
poieo eject tasks/keep-green.yaml
```

The task then points at a neighboring graph file. Graphs have four node types:

- `agent` asks a model and may give it tools;
- `command` runs a command or script;
- `router` chooses a branch from state;
- `confirm` asks a person before continuing.

A minimal graph looks like this:

```yaml
name: triage
version: 1
entry: classify
nodes:
  - id: classify
    type: agent
    role: classifier
    prompt: "Classify the request: {{ input.message }}"
    output:
      as: category
      into_state: category
    next: decide

  - id: decide
    type: router
    branches:
      - when: "state.category == 'bug'"
        to: investigate
    default: done

  - id: investigate
    type: agent
    role: investigator
    prompt: "Investigate: {{ input.message }}"

  - id: done
    type: command
    command: "echo no investigation needed"
```

Roles stay in the graph; concrete endpoints stay in the binding. State,
templates, retries, output destinations, task chaining, and failure policy are
described in [graphs](graph.md), [runtime](runtime.md), and [resident
execution](daemon.md).

## If something fails

Start with the narrowest check:

```bash
poieo validate tasks/<task>.yaml
poieo check
poieo run tasks/<task>.yaml --verbose
poieo runs show <run-id>
```

Specification errors name the file and rejected field. Provider failures say
which endpoint or role failed. Recorded runs retain structured failure causes
and the event stream even when a run does not complete.

Before unattended use, keep task folders under version control, validate every
edited task or graph, probe model bindings, set deadlines and spend limits
appropriate to the machine, and exercise the exact task once. The current
safety and non-goals are summarized in [DESIGN.md](../DESIGN.md).
