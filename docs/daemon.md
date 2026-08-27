# Daemon — residency

`src/poieo/daemon/` — `config.py`, `triggers.py`, `cron.py`, `service.py`

The daemon keeps flows firing until it is told to stop. It is the only component
that is long-lived, and most of its design is about that: everything is checked
before anything is armed, and nothing that happens during a run may take the
process down.

## Config

```
ProjectSpec              (project.py)   store · binding · tasks · learn
   └── DaemonConfig                     + flows[], read as flows
```

One schema, read to the depth the caller needs. A command asking "where is the
store" has no business loading triggers and graphs, so `ProjectSpec` leaves
`flows` as written; `DaemonConfig` narrows the field when something actually
intends to run them. A key therefore cannot mean one thing to `poieo run` and
another to `poieo daemon`.

A `FlowSpec` is one workflow wired to a trigger:

| key | is |
|---|---|
| `graph` | the graph file (or the card that stands in for one) |
| `binding` | falls back to the daemon-level default |
| `trigger` | `manual` · `interval` · `cron` · `loop` |
| `workdir` | where this flow's agent nodes work — and what gets a private copy |
| `input` / `input_file` | static payload; the file is re-read before each run |
| `carry_state` | the ending state of one run seeds the next |
| `isolation` | where its commands may run |
| `on_error` | `continue` (default) or `stop` |
| `then` | which flow should work next — see *Handoff* below |

`config_for_tasks_folder()` is what `poieo daemon <folder>` stands for: run the
cards in that folder. The argument says *which cards*, never *where the project
begins* — so a `poieo.yaml` above still answers that, and the config becomes that
project with its tasks folder swapped (same store, same binding, same memory).
Joining a project halfway, taking its memory but not the model it reads with, is
the kind of rule nobody can hold in their head.

## Loading is the preflight

`load_flows()` is where *fail at launch, not at 3am* is enforced. For every
enabled flow it parses the graph and binding (caching both by path, so ten cards
sharing a binding load it once), checks the workdir exists, runs
`preflight()` (roles resolve, agent nodes have somewhere to work) and
`check_credentials()`. Disabled flows are loaded but not credential- or
image-checked: they are not going to run, and refusing to *list* one would be
the check getting in the way of the fix.

It also **warns about roles the binding never heard of** — naming the roles, the
binding, and the model they will actually run on. A typo in a role name is not
an error, because falling back to `default` is what a default is for; it is just
the one silent way a graph gets an expensive model it never asked for. See
[binding.md](binding.md).

`_load_tasks()` expands the tasks folder first, in two passes — a card's
generated prompt names the cards it may tell, and that roster is not known until
the whole folder has been read. It also calls `check_memory()`, so a typo in a
memory entry fails here rather than at 3am.

## Triggers

Each trigger is an **async generator** that yields a `Firing` and only resumes once
the run has finished. That resume-after-run property is what makes `loop` a true
"run continuously" mode instead of a queue piling up behind a slow model.

| type | fires |
|---|---|
| `interval` | every `every`, on an absolute grid |
| `cron` | on a 5-field expression, local time |
| `loop` | back to back, pausing for `cooldown` |
| `manual` | only when something asks |

All four take `max_iterations`. Durations parse from `"30s"`, `"5m"`, `"2h"`,
`"1d"` or a bare number — and they parse **in the validator**, not in `build()`,
so a schedule that cannot be read fails where `poieo validate` can see it.

`IntervalTrigger` anchors to a grid from its origin, so a run that overran does
not shift every later tick, and ticks that fully elapsed are skipped rather than
queued. It always advances by at least one tick: a timer that woke a hair early
(Windows' clock is coarse) would otherwise land back on the tick just fired and
turn one period into two.

`cron.py` implements the standard 5 fields with `*/n`, ranges, lists, `mon-fri`
names, and the day-of-month **or** day-of-week rule.

## FlowRunner

One per flow. Its loop is `trigger → run → carry state → repeat`, and everything
interesting is in what surrounds the run.

**The ear.** `_next_fire()` races the trigger against the board's verbs.
A run-now wins over everything, even a hold. A hold stops the trigger from being
*consumed* at all, so a `loop` trigger sits suspended at its yield instead of
spinning through a pause — and at most one already-due fire is dropped in favour
of the next scheduled one. Fires that come due while paused are **skipped, not
queued**.

**The control seam.** `pause()`, `resume()` and `run_now()` are three flags and
an `asyncio.Event`, read between runs. That is the whole mechanism, and it can be
that small because the web server shares the daemon's event loop. `run_now()`
returns `False` mid-run: iterations never overlap, exactly as the triggers
promise. Control touches runtime state only — no file, no schedule on disk,
nothing that survives a restart.

**The private copy.** `_open_change()` and `_close_change()` bracket the run; see
[workspace.md](workspace.md). A repository that cannot be tracked is logged and
the work happens in place — not a reason to stop working at 3am.

**Failing the same way.** `_note_outcome()` counts consecutive failures sharing
one `cause.slug` (or the raw error text when nothing classified), so "Ollama down
at 2am" counts as one thing however its message varies. After `PAUSE_AFTER = 3`
the flow pauses itself and journals why. It parks rather than standing down —
the coroutine has to stay alive for `resume()` to have anyone to wake. `resume()`
also resets the counter, so a resumed flow does not trip again on its first bad
run.

`RESULTS_KEPT = 20` bounds the in-memory result history: a `RunResult` carries a
run's whole outputs and state, and only the tail is ever read.

## Daemon

Owns the pools, the containers, the runners, and the shutdown handshake.

- **one `ProviderPool` per distinct binding file**, so clients are reused across
  flows; **one container pool**, built only if some flow asks for isolation
- `_tool_context_for()` assembles each flow's `ToolContext` — its isolation setting, the
  shared container pool, and a `Postbox` if and only if its card took the `notes`
  toolset
- the web server, if a port was given, runs as a task on the same loop; the port
  is bound-checked up front so it fails at launch rather than after flows start
- `SIGINT`/`SIGTERM` sets `cancel`, which drains in-flight runs; a second signal
  exits immediately. Windows has no `add_signal_handler`, and that is caught
- `asyncio.gather(..., return_exceptions=True)`: one flow blowing up must not
  orphan the others or tear down pools they are still using
- on the way down, background tasks are awaited with a grace period and their
  failure is *logged*, not swallowed — a learning pass that blew up at 3am used
  to go down with the daemon without leaving a word behind

## The learning loop

`learn: 1d` in the config starts a background loop that runs a pass while
**nothing else is running** — `_ready_to_learn()` requires every runner to be
`waiting`. It is a double opt-in: the config key *and* the `memory/longterm/`
folder. Half an opt-in is how a feature dies quietly, so a config that says
`learn:` over a project with no memory folder logs a warning naming both. See
[memory.md](memory.md).

## Handoff

`then:` on a flow is the router's `branches`, one level up: `graph.Branch`
imported rather than redeclared, so `when` / `to` / `label` mean there what they
mean inside a graph. There is no `default` — a router needs one because a run has
to go somewhere, and a finished run does not. Falling off the end is what almost
every flow does; a catch-all is a last branch reading `"true"`.

```yaml
# tasks/chores.yaml
name: chores
folder: ~/code/poieo
prompt: Find one thing worth fixing, fix it, run the tests.
then:
  - when: "run.change"
    to: review
    label: something changed
```

### What is checked at load

`check_handoffs()` runs after the tasks folder is read (a card becomes a flow
only at that point, and a handoff is entitled to name one):

- a target that is not a flow is a **startup error**, and the message lists what
  there is
- a flow pointing at itself is a **startup error** — `loop` and `carry_state` are
  what a flow's own next run is for
- a disabled target **warns**; `enabled: false` is the off switch and may well be
  deliberate
- a cycle **warns** and still loads: review → fix → review is a legitimate
  feedback loop, and `MAX_CHAIN` is what bounds it
- handing off from a `loop` trigger **warns**, since everything downstream
  inherits that pace

### What happens when a run ends

`Daemon._hand_off()` is bound into every runner, and fires after the run —
**ahead of any stand-down**, because the run happened and what it says should
work next does not depend on whether this runner carries on. A flow that pauses
itself on a third failure is exactly the one whose `broke` branch someone wanted.

1. `handoff_scope(result)` builds what a branch may test. **One shape, not two**:
   whatever the condition could ask about, the run it starts reads as
   `input.sender`. `usage` is left out — nothing branches on a token count — and
   `change` is present-and-`None` rather than absent, because `when: "run.change"`
   is the commonest branch there is and it has to read false rather than raise.
2. `_chosen()` evaluates the branches router-style, first match wins. **A branch
   that will not evaluate is skipped, not fatal.** A router raises and takes the
   run with it, which is right while a run is still going; here the sender has
   already finished and landed its change, so there is nothing left to fail. The
   next branch gets its turn and the mistake is logged against the flow that made
   it.
3. The target is woken by `hand()`, which — unlike `run_now()` — does not refuse
   mid-run. It **parks**, and the run loop finds it when the current run ends.

The payload key is **`sender`, not `from`**: conditions and templates are parsed
as Python, where `from` is a keyword, so `input.from.change` would not even
parse. It is also what `tools/notes.py` already calls the other end of a message.
It is merged last, after the static input and the card's payload — what woke this
run is the most specific thing it knows.

### The four rules that bound it

- **One handoff waits, and the newest wins.** That is the interval trigger's rule
  one level up: a flow that has fallen behind should work on the latest thing,
  not grind through a backlog it can never clear. Every displaced handoff is
  logged, because a loss nobody hears about is exactly what that rule would
  otherwise buy.
- **A paused target is not woken.** A handoff is not a reason to override a hold
  someone put on.
- **A chain stops after `MAX_CHAIN` (10) hops.** The same guard `max_steps` is
  inside a graph, for the same reason: a loop between flows is legitimate,
  running forever is not. Depth rides on the `Handoff` so no flow has to know how
  it was reached.
- **A disabled target is silently skipped.** It has no runner, and
  `check_handoffs()` already said so at load; saying it again per run would be
  noise.

`RunResult.trigger` records **what actually fired the run** (`fire.reason`),
not the schedule it may not have used — so a run-now on a cron flow no longer
records the cron, and a handoff records `after <sender> (<label>)`. That is what
lets a run be traced back to the run that caused it.
