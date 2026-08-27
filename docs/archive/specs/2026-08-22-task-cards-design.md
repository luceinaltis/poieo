# Task Cards and the Journal

**Date:** 2026-08-22
**Status:** Approved for planning
**Roadmap:** step 4 (web control plane) — the file format the board edits
**Depends on:** the checkpoint backend (`2026-08-22-nightly-review-design.md`)

## Goal

Two things, one small enough to ship together.

**A task is one file.** A name, a folder, and a prompt — that is everything a
user must write to have work running around the clock. Everything else has a
default.

**A task remembers.** Each one keeps a journal of what it has already done and
what the user has told it, and it reads that journal before every run. So the
morning's *discard* is tonight's instruction, and a task stops re-doing work it
already did.

Today neither exists: starting one folder-tending task takes three hand-written
files, and the only two verbs the review offers — accept and discard — leave no
trace the model can read.

## Decisions already made

- **A task is sugar over a flow plus a graph**, not a second config format. It
  expands at load time into objects indistinguishable from hand-written ones;
  nothing downstream of the loader learns that tasks exist.
- The sugar is **visible** (`poieo show` renders what a task expands to) and
  **reversible** (`poieo eject` writes that graph out and hands it over).
- Tasks live in a folder named by `poieo.yaml`. The explicit `flows:` list
  keeps working, unchanged, beside them.
- **Default schedule is `every: 1h`.** Chosen for safety: a task pointed at a
  cloud binding must not surprise anyone with an overnight bill, and "keeps
  turning" is one line away (`every: loop`).
- The journal is **plain markdown next to the task file**, append-only, and
  editable by hand. A line the user types works exactly like a line poieo
  appended.
- Accept and discard gain **one optional note each**. That is the only new
  mutation surface in this design.

## Vocabulary check

DESIGN principle 7 fixes three words: **task**, **work**, **change**. The
journal must not become a fourth.

It does not, because the user never meets it as a separate object. On the card
it is a section under the prompt — *what this task remembers* — and in the file
system it is a file with the task's own name. Nobody has to learn a noun to use
it: they type a sentence in the box next to *discard*, and the task knows it
next time.

The review spec's banned words still stand. `commit`, `branch`, `worktree`,
`run id` do not appear in a journal line.

## Out of scope

- **Task CRUD from the browser.** This design produces the file the control
  plane will create and edit; the routes that do it are the next slice.
- **Multi-node tasks.** A task is exactly one step with hands. Anything more
  structured ejects to a graph and is edited as one.
- **Journal compaction.** Old lines are not summarised or rewritten, only
  capped on the way into the prompt.
- **Per-task provider configuration** beyond naming a role and a binding file.

## The task file

```yaml
# tasks/keep-improving.yaml
name: keep improving poieo
folder: ~/code/poieo
prompt: |
  Find one thing worth fixing, fix it, run the tests.
```

Three required keys. Everything below is optional and defaulted:

| key | default | is |
|---|---|---|
| `every` | `1h` | `30m`, `2h`, or `loop` for back-to-back |
| `at` | — | a cron expression; mutually exclusive with `every` |
| `role` | the binding's default | which role in the binding does the work |
| `tools` | `[files, shell]` | which toolsets the model gets |
| `max_turns` | `40` | steps the model may take in one piece of work |
| `enabled` | `true` | disarm without deleting |
| `binding` | the daemon's | override the model mapping for this task alone |
| `graph` | — | set by `eject`; forbidden together with `prompt`/`tools`/`max_turns` |

`poieo.yaml` learns exactly one key:

```yaml
store: .poieo
binding: models/local.yaml
tasks: tasks/          # every *.yaml in here is a card
flows: [ ... ]         # unchanged
```

**Identity comes from the filename, not the title.** `tasks/keep-improving.yaml`
is the task `keep-improving` forever; `name:` is a display string the user may
rewrite at will. Renaming the title must never orphan a task's history or its
private copy, and this is what guarantees it.

## What it expands into

| task key | lands on |
|---|---|
| filename stem | the flow's name |
| `folder` | the flow's `workdir` — so the checkpoint layer gives the run a private copy |
| `every` / `at` | the flow's trigger (`interval` / `loop` / `cron`) |
| `binding`, `enabled` | the flow's own |
| — | `carry_state: true`, always |
| `prompt`, `role`, `tools`, `max_turns` | the single agent node |

The generated graph is one node:

```yaml
name: keep-improving
entry: work
nodes:
  - id: work
    type: agent
    role: <role>
    tools: [files, shell]
    max_turns: 40
    system: <the block below>
    prompt: <the user's prompt, verbatim>
    output: {as: summary}
    next: null
```

The node names no `workdir`: it inherits the run's, which is the private copy.
This depends on the checkpoint design's rule that an agent node without a
`workdir` takes the run's — if that rule is not in place when this is
implemented, it is a prerequisite, not an option. The point is that a task
**cannot** be pointed at the user's own checkout by accident.

The generated `system` block is user-visible behaviour, so it is fixed here:

```
You are working on <name>, in a private copy of <folder>.

What you have already done, and what the user has told you:
<the journal's last 20 lines, or "nothing yet">

Finish by saying in one line what you did. If there was nothing worth
doing, say that in one line instead.
```

## The journal

One file per task, same name, beside it: `tasks/keep-improving.md`. Created
empty on first run.

```markdown
- 2026-08-22 03:14 · did      fixed the flaky interval test on Windows (+12 / -4)
- 2026-08-22 04:20 · did      corrected two typos in README (+2 / -2)
- 2026-08-22 06:05 · failed   the model could not be reached
- 2026-08-22 08:02 · you      discarded the 04:20 work — "leave prose alone,
                              spend the night on tests"
- 2026-08-22 09:30 · nothing  found nothing worth doing
```

**Written by poieo, one line per event, appended and never rewritten:**

| kind | when | carries |
|---|---|---|
| `did` | work succeeded and changed something | the model's own one-line summary, plus the change's size |
| `nothing` | work succeeded and changed nothing | the model's line |
| `failed` | work failed | the failure's first line |
| `you` | the user accepted or discarded **with a note** | the verb, what it applied to, and the note |

A note-less accept or discard writes nothing. The user may also open the file
and write a line themselves at any time.

**Read** before every run — re-read each time, like `input_file` already is, so
a note written at 8am is in effect at 9am. Only the **last 20 lines** go into
the prompt, preceded by `(earlier entries omitted)` when there are more. The
file itself is never truncated.

poieo does not parse the journal on the way in. It reads the tail as text and
drops it into the prompt, which is what makes hand-written lines work.

### Shipped so far

The journal, its four line kinds, and reading the tail into every run are in.
Two pieces wait on the checkpoint backend, which is unmerged:

- **`nothing`** cannot be told from `did` yet. Whether a run changed anything is
  a checkpoint question, so every finished run currently writes `did`.
- **The `note` field on accept and discard** has no route to sit on. Until it
  does, `poieo note` is how a user adds a `you` line -- the same function, a
  different door.

## Interfaces

**CLI**

| command | does |
|---|---|
| `poieo tasks [config]` | list the cards: name, folder, schedule, enabled, and the journal's last line |
| `poieo show tasks/x.yaml` | render what the task expands to |
| `poieo run tasks/x.yaml` | run it once |
| `poieo eject tasks/x.yaml` | write `graphs/x.yaml`, rewrite the task to name it |

`poieo validate` covers tasks already, because they load with the daemon config.

**HTTP** — one optional field on each of the review's two routes:

```
POST /api/flows/{flow}/accept    {through_run_id?, note?}
POST /api/flows/{flow}/discard   {from_run_id?, note?}
```

A present, non-empty `note` appends a `you` line. Nothing else changes.

## Failure handling

| situation | behaviour |
|---|---|
| `folder` does not exist | load-time error, like every other misconfiguration (principle 5) |
| `folder` is not a repository | the checkpoint design's answer — the task runs, its work cannot be reviewed, the card says so |
| both `prompt` and `graph` | load-time error naming the file |
| both `every` and `at` | load-time error |
| a task's name collides with an explicit flow | load-time error; neither silently wins |
| journal file missing | created empty; the run proceeds |
| journal unreadable (permissions, bad encoding) | the run proceeds without it, and the failure is logged once — memory is not worth killing a night's work over |
| `eject` on a task that already names a graph | refused, nothing written |
| `eject` target file exists | refused, nothing written |

## Testing

- **Expansion is golden**: a task and its hand-written equivalent produce equal
  `FlowSpec`/`GraphSpec` objects. That equality is the whole safety argument for
  the sugar, so it is asserted directly.
- A task-backed daemon run and the hand-written equivalent produce the same run
  log, event for event.
- Journal: a line appended for each of `did` / `nothing` / `failed`; a note
  appended by accept and by discard; no line for an empty note; the last-20
  window; hand-written lines surviving a round trip.
- `eject` round trip: eject, then run — same behaviour, and the task file's
  remaining keys still apply.
- Every refusal path in the table above.
- Runs from an explicit `flows:` entry must be byte-for-byte unaffected.

## Implementation split

- **Plan D1 — the task file.** `poieo.task` (`TaskSpec`, `expand`), the
  `tasks:` key, `poieo tasks` / `show` / `run` / `eject`. Verifiable from the
  command line alone, with no journal anywhere.
- **Plan D2 — the journal.** Reading it into the generated system block,
  appending the four line kinds, the `note` field on the two review routes.

Both land after the checkpoint backend, which supplies `workdir` and the routes
D2 extends.
