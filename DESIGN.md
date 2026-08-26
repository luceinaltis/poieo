# poieo Design

> This document describes **what poieo must provide to its user**.
> How each component actually works lives in `docs/`, one document per
> component; `docs/README.md` is the index.

## One line

**An autonomous task board: write down the work you want done, and the LLMs on
your own machine keep it running around the clock.**

The user designs the flow of the work, poieo keeps that flow resident, and the
model does the actual hands-on work at each step. Pin up a task like "keep
improving this project" and — find something to fix, edit the code, run the
tests, branch on the result — the flow keeps turning while you are away.

## Core principles

### 1. Logical / physical separation

**What the work is** (graph) and **which model does it** (binding) are two
separate files. A graph names roles; a binding maps roles onto real models.
Moving a workflow designed against a 3B laptop model onto Claude Opus is one
flag.

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
under `.poieo/`, rebuilt from the files at any time and safe to delete.
Everything that means something versions with git, and
the CLI and web UI read the same files — work started in one interface can be
continued in any other.

### 5. Fail at launch, not at 3am

Every graph, binding, and expression is validated at load time. A typo must
never kill a flow when its trigger fires in the middle of the night. In the
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

A run is one pass from the entry node to a node with nowhere left to go, and
it is called that everywhere — on screen, in `poieo runs`, and in the log. The
board used to say "a piece of work" for what the files called a run: one thing
with two names, which is the exact tax this principle exists to refuse.

Everything underneath — how a run is isolated, how a change is stored, how it
is undone — is machinery, and machinery does not appear in the interface. The
one exception is the moment the user's own files are about to change: there,
poieo says exactly what will happen to them. **Hide the mechanism, never the
result.**

## User experience

### Today: the CLI

```
poieo run      execute a graph once
poieo daemon   keep flows resident
poieo runs     see what happened
poieo validate / show / check   preflight everything
```

### Target: the web roadmap board

A single page that opens when you point a browser at wherever `poieo daemon`
is serving. From there the user can:

- **Create a task card** — write a name and a prompt, save, and the card
  starts running around the clock. A card *is* a flow.
- **See the roadmap** — every task's state at a glance: running / paused /
  last result.
- **Open the details** — expanding a card exposes the flow (graph) on a
  canvas editor, the trigger schedule, and the role→model mapping (binding).
  Unopened, it all stays on defaults.
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
| **Flow** — graphs, routers, cycles, state | a language for designing the order and branching of work | done |
| **Residency** — daemon, triggers, carried state | the designed flow keeps running, 24/7 | done |
| **Hands** — agent node, files/shell tools | the model doesn't just talk about an edit; it makes it and runs the tests | done |
| **Undo** — work isolated from the user's files, one change per run | last night's work arrives as a diff to accept or throw away, never as a surprise | done |
| **Fences** — opt-in container isolation for a task's commands | the hands reach the folder and nothing else of the machine | done |
| **Word of mouth** — a task can leave a line in another task's journal | tasks that stand alone can still tell each other what changed | done |
| **Memory** — a project keeps what it has learned, and every task reads it before working | last month's lesson is in front of tonight's run, and you can open the file it came from | done |
| **Face** — the web roadmap board | all of the above in a browser, with minimal configuration | most: observe, review and control are live; creating a card from the board is next |

The key insight: **"keeps working" is a property of the flow, not of a node.**
An agent node is one step of the flow using its hands; running forever is the
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
- **Time**: every unbounded thing has a ceiling — how many steps a flow may
  take, how many turns a model may spend on one step, how long a command may
  run. Endless wandering becomes a recorded failure, and the next trigger
  starts fresh.
- **Cost**: every run's token usage is recorded. With local models this is
  free in practice; when a cloud model is bound, the spend is visible.

## Non-goals

- **Not a multi-user service.** One person's machine, that person's work.
  No auth, no permissions, no team features.
- **No database of record.** Files are the sole source of truth. A derived
  index may exist under `.poieo/`, gitignored, rebuilt from the files at any
  time; deleting it loses nothing, and nothing is ever true because the
  index says so.
- **Not a general-purpose agent framework.** The goal is not to compete with
  LangChain-style abstraction stacks, but to complete one experience: *my
  work keeps running on my machine*. Node types and tools grow only as far
  as that experience requires.
- **No OS-level sandbox by default.** Path confinement is the default; real
  isolation is opt-in, never a prerequisite for getting started. (See safety
  boundaries.)

## Roadmap

Items 1–5, 7 and 8 have shipped, and 6 is half-shipped: flow control
(pause / resume / run-now) is live end to end; task card CRUD is the open
slice. The link after each shipped item is the document describing how it
works today.

1. **Agent node** — build the hands: file and shell tools confined to a
   working directory. Tool execution sits behind a swappable seam from day
   one, so container isolation can arrive later without reshaping anything.
   (`docs/tools.md`)
2. **Observation** — an HTTP server inside the daemon streaming run events to
   a browser: what is running, which node, every tool call, what the model
   said. Read-only.
   (`docs/web.md`)
3. **The morning review** — the model works in a private copy; each run is one
   reviewable change; the board shows the diff and accepts or discards it.
   This is where the daemon stops being something you have to trust blindly.
   (`docs/checkpoint.md`)
4. **The task card** — a task becomes one file (a name, a folder, a prompt),
   and it keeps a journal of what it did and what the user told it, which it
   reads before every run. This is what principle 2 promises and what the
   board edits.
   (`docs/tasks.md`)
5. **Isolation** — a task can opt into running its commands in a container
   that sees its folder and nothing else of the machine. The shell was the
   one tool that could reach past path confinement; this closes it.
   (`docs/tools.md`)
6. **Web control plane** — task card CRUD and flow control (REST API); fold
   the existing canvas editor in for detail editing. The daemon gains runtime
   flow add/remove/pause. Flow control — pause, resume, run now, from runner
   to board — has shipped; CRUD and the editor fold-in remain.
   (`docs/web.md`)
7. **Tasks that work together** — a task can leave a line in another task's
   journal, read on that task's next run. News, not orders, and no way to
   spin: a note wakes nobody.
   (`docs/tasks.md`)
8. **A long memory** — the project keeps one page that is always in front of
   every task, and a folder of things it has learned; every run leaves a
   full record behind, so anything remembered can be traced to the run that
   taught it.
   (`docs/memory.md`)
9. **Beyond (candidates)** — delegating steps to external agent CLIs
   (Claude Code, etc.); fan-out steps; run-log retention; stronger isolation
   backends (microVM, or the OS-level primitives Landlock and Seatbelt)
   behind the same seam.

The design specs and implementation plans these were built from are kept
under `docs/archive/`.
