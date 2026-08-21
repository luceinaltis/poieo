# poieo Design

> This document describes **what poieo must provide to its user**.
> Implementation detail lives in the per-feature specs under
> `docs/superpowers/specs/`.

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

The only things a user must write are **a task's name and its prompt**.
Everything else — which role serves it, when it runs, where output lands — has
a sensible default, opened and tuned only when detailed instructions are
actually needed.

Simple things take one line; complex things stay possible.

### 3. Local first

The primary target is a local LLM running on the user's machine (Ollama and
friends). That is what makes a 24/7 resident design viable — it has to be able
to run without worrying about token spend. Cloud models (the Claude API) plug
into the same binding mechanism as an option, never as a prerequisite.

### 4. Everything is a file, everything is inspectable

Graphs, bindings, task configuration, and run history are all human-readable
files (YAML/JSONL). There is no database. Everything versions with git, and
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

Edits are saved to files and picked up by the daemon from the next run.
No restarts.

## Capability layers

What poieo offers the user stacks in layers:

| layer | what the user gets | status |
|---|---|---|
| **Flow** — graphs, routers, cycles, state | a language for designing the order and branching of work | done |
| **Residency** — daemon, triggers, carried state | the designed flow keeps running, 24/7 | done |
| **Hands** — agent node, files/shell tools | the model doesn't just talk about an edit; it makes it and runs the tests | spec approved, next to build |
| **Face** — the web roadmap board | all of the above in a browser, with minimal configuration | after that |

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
  definition. What guards them is version control: the model's changes must
  be checkpointed per run so any night's work can be reviewed as a diff and
  rolled back. Autonomy without undo is a different, scarier product.
- **Time**: every unbounded thing has a ceiling — how many steps a flow may
  take, how many turns a model may spend on one step, how long a command may
  run. Endless wandering becomes a recorded failure, and the next trigger
  starts fresh.
- **Cost**: every run's token usage is recorded. With local models this is
  free in practice; when a cloud model is bound, the spend is visible.

## Non-goals

- **Not a multi-user service.** One person's machine, that person's work.
  No auth, no permissions, no team features.
- **No database.** Files are the source of truth.
- **Not a general-purpose agent framework.** The goal is not to compete with
  LangChain-style abstraction stacks, but to complete one experience: *my
  work keeps running on my machine*. Node types and tools grow only as far
  as that experience requires.
- **No OS-level sandbox by default.** Path confinement is the default; real
  isolation is opt-in, never a prerequisite for getting started. (See safety
  boundaries.)

## Roadmap

1. **Agent node** — build the hands: file and shell tools confined to a
   working directory. Tool execution sits behind a swappable seam from day
   one, so container isolation can arrive later without reshaping anything.
   (`docs/superpowers/specs/2026-08-21-agent-node-design.md`)
2. **Web control plane** — integrate an HTTP server into the daemon; task
   card CRUD and flow control (REST API); the roadmap board page; fold the
   existing canvas editor in for detail editing. The daemon gains runtime
   flow add/remove/pause.
3. **Beyond (candidates)** — container isolation (Docker); per-run
   checkpointing of the model's changes; delegating steps to external agent
   CLIs (Claude Code, etc.); fan-out steps; dependencies between tasks
   (roadmap ordering).
