# poieo Design

> This document describes **what poieo must provide to its user**.
> How each component actually works lives in `docs/`, one document per
> component; `docs/README.md` is the index.

## One line

**An autonomous task board: write down the work you want done, and the models
you choose keep it running around the clock.**

The user designs the shape of the work; the model does the hands-on part of each
step. Pin up a task like "keep improving this project" and — find something to
fix, edit the code, run the tests, branch on the result — it keeps turning while
you are away.

## Core principles

### 1. Logical / physical separation

**What the work is** (graph) and **which model does it** (binding) are two
separate files. A graph names roles; a binding maps roles onto real models.
Moving a workflow from the smallest model on a laptop to the largest one an API
sells is a flag, not an edit.

This separation is an invariant every new feature must respect. When the web
editor arrives, graph editing and binding editing stay distinct.

### 2. Minimal configuration

The only things a user must write are **a task's name, the folder it works
in, and its prompt**. Everything else — which role serves it, when it runs,
where output lands — has a sensible default, opened and tuned only when
detailed instructions are actually needed. (The folder stays explicit on
purpose: it is the one thing the model's hands will touch, and principle 7's
moment — "the user's own files are about to change" — must never be filled
in by a default.)

Simple things take one line; complex things stay possible.

### 3. Local first

The primary target is a local LLM running on the user's machine (Ollama and
friends). That is what makes a 24/7 resident design viable — it has to be able
to run without worrying about token spend. Cloud models (the Claude API) plug
into the same binding mechanism as an option, never as a prerequisite.

### 4. Everything is a file, everything is inspectable

Graphs, bindings, task configuration, and run history are all human-readable
files (YAML/JSONL). There is no database of record — at most a derived index
under `memory/cache/`, rebuilt from the files at any time and safe to delete.
Everything that means something versions with git, and
the CLI and web UI read the same files — work started in one interface can be
continued in any other.

### 5. Fail at launch, not at 3am

Every graph, binding, and expression is validated at load time. A typo must
never kill a task when its trigger fires in the middle of the night. In the
other direction, **an in-run failure never kills the daemon** — it is
recorded, and the next trigger starts a fresh run. Staying up is the default.

### 6. You can always see what it did

An autonomous system is only trustworthy if it is auditable. Every run records,
event by event, which model answered, which branch a router took, what tokens
were spent, and — once the model has hands — **which files it touched and
which commands it ran**. "What did this thing do last night?" must be
answerable from a single log file.

### 7. A small vocabulary

Minimal configuration (principle 2) is worth little if understanding the
result takes a manual. The user learns three words and no more: a **task**
(a name, a prompt, a folder), a **run** (one pass through it — succeeded,
failed, or found nothing to do), and a **change** (what that run did to the
files, which you accept or discard).

A run is one pass from the entry node to a node with nowhere left to go, and it
is called that everywhere — on screen, in `poieo runs`, and in the log. One
thing with two names is the exact tax this principle exists to refuse.

Everything underneath — how a run is isolated, how a change is stored, how it
is undone — is machinery, and machinery does not appear in the interface. The
one exception is the moment the user's own files are about to change: there,
poieo says exactly what will happen to them. **Hide the mechanism, never the
result.**

## User experience

### Today: the CLI

Everything is reachable from a terminal, and the commands are grouped by what a
person is doing rather than by which layer they touch: **setting up** a project
and choosing which models answer, **your tasks** — see the board, try one, tell
one something, keep them all running — and **what happened**, the runs and what
the project has learned from them.

`poieo --help` is the list. Naming each command here would be a second copy of
it, and the copy is the one that goes wrong.

### Target: the web roadmap board

A single page that opens when you point a browser at wherever `poieo daemon`
is serving. From there the user can:

- **Create a task card** — write a name and a prompt, save, and the card
  starts running around the clock. Writing it is the only step; there is
  nothing else to register it with.
- **See the roadmap** — every task's state at a glance: running / paused /
  last result.
- **Open the details** — expanding a card exposes its graph on a canvas
  editor, the trigger schedule, and the role→model mapping. Unopened, it all
  stays on defaults.
- **Control** — pause/resume, run once right now.
- **Observe** — replay run history, including the model's tool activity.
- **Review the night** — open a run, read the change it made as a diff, and
  accept it or throw it away. Until it is accepted, nothing the model wrote
  has touched the user's own files.

Edits are saved to files and picked up by the daemon from the next run.
No restarts.

## Capability layers

What poieo offers the user stacks in layers:

| layer | what the user gets | status |
|---|---|---|
| **Graph** — nodes, routers, cycles, state | a language for designing the order and branching of work | done |
| **Binding** — every engine on the machine found once, and named in one file | the models are a pool you pick a step's model from, not a name you had to remember | done |
| **Residency** — daemon, triggers, carried state | the graph you designed keeps running, 24/7 | done |
| **Hands** — a step that can read, write and run commands | the model doesn't just talk about an edit; it makes it and runs the tests | done |
| **Undo** — work isolated from the user's files, one change per run | last night's work arrives as a diff to accept or throw away, never as a surprise | done |
| **Fences** — opt-in container isolation for a task's commands | the hands reach the folder and nothing else of the machine | done |
| **Word of mouth** — a task can leave a line in another task's journal | tasks that stand alone can still tell each other what changed | done |
| **Memory** — a project keeps what it has learned, and every task reads it before working | last month's lesson is in front of tonight's run, and you can open the file it came from | done |
| **Face** — the web roadmap board | all of the above in a browser, with minimal configuration | part built |

The key insight: **"keeps working" is a property of the graph, not of a node.**
An agent node is one step of the graph using its hands; running forever is the
job of the user-designed graph plus the daemon's triggers, with progress
carried between iterations as state.

## Safety boundaries

Autonomous execution needs explicit fences:

- **Space**: tools cannot reach outside the task's designated working
  directory. By default that fence is path checking — it prevents accidents,
  not a malicious model. A task can opt into container isolation (Docker),
  where only the working directory is visible and nothing else on the machine
  is reachable at all. Isolation stays opt-in because it costs setup and
  per-task images, which the minimal-configuration principle refuses to
  impose by default.
- **Recovery**: isolation protects everything *outside* the working
  directory; the files *inside* it are the work, so they are exposed by
  definition. What guards them is version control, in two moves. The model
  works in a **private copy** of the project, so the user's own files are
  never touched while they sleep. Each run's changes are **checkpointed as
  one reviewable change**, so a night's work can be read as a diff and either
  accepted into the project or thrown away. This is not a later luxury: it is
  what makes hands safe to hand out, and it ships with them. Autonomy without
  undo is a different, scarier product.
- **Time**: every unbounded thing has a ceiling — how many steps a task may
  take, how many turns a model may spend on one step, how long a command may
  run. Endless wandering becomes a recorded failure, and the next trigger
  starts fresh.
- **Cost**: every run's token usage is recorded. With local models this is
  free in practice; when a cloud model is bound, the spend is visible.

## Non-goals

- **Not a multi-user service.** One person's machine, that person's work.
  No auth, no permissions, no team features.
- **No database of record.** Files are the sole source of truth. A derived
  index may exist under `memory/cache/`, gitignored, rebuilt from the files at
  any time; deleting it loses nothing, and nothing is ever true because the
  index says so.
- **Not a general-purpose agent framework.** The goal is not a stack of
  abstractions to build anything on, but one experience carried through: *my
  work keeps running on my machine*. Node types and tools grow only as far as
  that experience requires.
- **No OS-level sandbox by default.** Path confinement is the default; real
  isolation is opt-in, never a prerequisite for getting started. (See safety
  boundaries.)

Each of these was a good idea. At WWDC 1997 Jobs said focus "means saying no
to the hundred other good ideas that there are"; at the same event, defending
the end of a technology he granted did "some things ... that nothing else out
there does," he gave the test he used instead — "you've got to start with the
customer experience and work backwards to the technology" — and admitted he
had made the opposite mistake more than anyone else in the room. So the
question for anything proposed is neither whether it is good nor whether it is
unique. It is whether a line runs from it back to *my work keeps running on my
machine*. **When no line can be drawn, the idea belongs on this list, not on
the roadmap.**

## Roadmap

What is not built yet. Everything marked done in the table above is, and how
each of those works *today* is in its component document — a roadmap that also
described finished work would be a second, staler account of it.

- **The board writes, not only reads.** Creating a card from the browser is
  live, and so is setting one aside — recoverably, the card moved whole rather
  than deleted. What is left: editing a card's fields from the page, and
  folding the existing canvas editor into the detail view.
- **Beyond, as candidates.** Delegating a step to an external agent CLI;
  fan-out steps; deciding what happens to run logs as they age; stronger
  isolation backends behind the seam the current one already sits on.

The design specs these were built from are kept under `docs/archive/`. They
record what was intended at the time, which is not always what is true now.
