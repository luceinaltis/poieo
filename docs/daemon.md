# Daemon — residency

`src/poieo/daemon/` — `config.py`, `triggers.py`, `cron.py`, `service.py`

The daemon keeps tasks firing until it is told to stop. It is the only component
that is long-lived, and most of its design is about that: everything is checked
before anything is armed, and nothing that happens during a run may take the
process down.

## Config

```
ProjectSpec              (project.py)   store · binding · tasks · learn
   └── DaemonConfig                     + tasks[], read as tasks
```

One schema, read to the depth the caller needs. A command asking "where is the
store" has no business loading triggers and graphs, so `ProjectSpec` leaves
`tasks` as written; `DaemonConfig` narrows the field when something actually
intends to run them. A key therefore cannot mean one thing to `poieo run` and
another to `poieo daemon`.

A `TaskSpec` is one workflow wired to a trigger:

| key | is |
|---|---|
| `graph` | the graph file (or the card that stands in for one) |
| `binding` | falls back to the daemon-level default |
| `trigger` | `manual` · `interval` · `cron` · `loop` |
| `workdir` | where this task's agent nodes work — and what gets a private copy |
| `input` / `input_file` | static payload; the file is re-read before each run |
| `carry_state` | the ending state of one run seeds the next |
| `isolation` | where its commands may run |
| `on_error` | `continue` (default) or `stop` |
| `then` | which task should work next — see *Handoff* below |

A folder **with a `poieo.yaml` in it** is that project — `poieo daemon ../notes`
is how a second project gets named, and reading a project root as a folder of
cards would try to load its own marker as a task. A folder **without** one is
what `config_for_tasks_folder()` stands for: run the cards in that folder. The argument says *which cards*, never *where the project
begins* — so a `poieo.yaml` above still answers that, and the config becomes that
project with its tasks folder swapped (same store, same binding, same memory).
Joining a project halfway, taking its memory but not the model it reads with, is
the kind of rule nobody can hold in their head.

## Loading is the preflight

`load_tasks()` is where *fail at launch, not at 3am* is enforced. For every
enabled task it parses the graph and binding (caching both by path, so ten cards
sharing a binding load it once), checks the workdir exists, runs
`preflight()` (roles resolve, agent nodes have somewhere to work) and
`check_credentials()`. Disabled tasks are loaded but not credential- or
image-checked: they are not going to run, and refusing to *list* one would be
the check getting in the way of the fix.

It also **warns about roles the binding never heard of** — naming the roles, the
binding, and the model they will actually run on. A typo in a role name is not
an error, because falling back to `default` is what a default is for; it is just
the one silent way a graph gets an expensive model it never asked for. See
[binding.md](binding.md).

`_load_cards()` expands the tasks folder first, in two passes — a card's
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

Both of those live in `_next_tick(tick, elapsed, every)` as a function so the
invariant can be tested as arithmetic — timing the gaps between fires cannot
answer it on a loaded machine.

`cron.py` implements the standard 5 fields with `*/n`, ranges, lists, `mon-fri`
names, and the day-of-month **or** day-of-week rule.

## TaskRunner

One per task. Its loop is `trigger → run → carry state → repeat`, and everything
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

**A run re-reads both files it answers to first.** `Daemon.refresh()` is called
before every firing, beside `read_input` and for the same reason: what the run
needs is read now rather than remembered from startup. An edit — `poieo config
use`, a hand edit, a pull, and now a changed prompt — is in effect on the next
run rather than after a restart, which is what [DESIGN.md](../DESIGN.md)
promises.

A card carrying its own prompt is re-expanded from the card file; a task
naming a graph file re-reads that.

**Only the graph is adopted, and only when nothing else changed.** A card expands
into a spec *and* a graph, and the two split fields a reader would call one
thing: `tools:` lands on the node, `isolation:` and `folder:` on the spec.
Adopting the graph alone would honour a card's new tools while ignoring the
isolation it asked for in the same edit — shell on the host rather than in a
container — and would tell the model it works in a folder the tools are not
rooted in. So a card whose expansion changed anything but its graph is refused
and says so. A schedule, a folder or an `enabled:` still wants a restart, and
adding a card at runtime is its own piece of work.

**Both files are attempted, and the graph runs both startup checks.** Each is
read in its own attempt, so a half-written binding cannot silently freeze the
graph's reread, and the warning names whichever failed. `check_credentials` runs
beside `preflight`: a graph reaching a role whose key is unset would otherwise be
adopted, die opening the provider, and then make every later binding reread raise
on the roles it had just added — a task stuck until restart by a file it read
itself.

`reread(key)` stays beside it and stays a key: the board writes a binding file
and asks for that one back (`POST /api/projects/{p}/models/use`), which is a
different question from "everything this run answers to". Two callers, two doors.

It is the **daemon's** reread and not the runner's, because one file is one spec
across every task that names it: a runner reading only for itself would leave its
siblings on the old model until each happened to fire, and the board would paint
that as a mix — harder to read than uniform staleness.

The new spec is **validated before it is adopted**, with the two checks
`load_tasks` runs at startup and in its wording: a file saved mid-flight must not
put the daemon somewhere it would have refused to start. A file that will not
load, or would not have armed this task, is a **warning and no more** — the spec
in memory is still valid and still what the board is claiming, and 3am is no time
to stop over a config caught half-written.

The pool keeps its clients through all of this; [binding.md](binding.md) says why.

**Failing the same way.** `_note_outcome()` counts consecutive failures sharing
one `cause.slug` (or the raw error text when nothing classified), so "Ollama down
at 2am" counts as one thing however its message varies. After `PAUSE_AFTER = 3`
the task pauses itself and journals why. It parks rather than standing down —
the coroutine has to stay alive for `resume()` to have anyone to wake. `resume()`
also resets the counter, so a resumed task does not trip again on its first bad
run.

`RESULTS_KEPT = 20` bounds the in-memory result history: a `RunResult` carries a
run's whole outputs and state, and only the tail is ever read.

## Daemon

Owns the pools, the containers, the runners, and the shutdown handshake.

Its roster is a list of **`LoadedProject`** — a config, a run store, and that
project's tasks. `poieo daemon a/ b/` is how it gets more than one. Anything
whose answer differs per project asks the project: where a run is written, which
cards a note may reach, whether this project learns. Anything shared by the
machine stays on the daemon: the pools, the container pool, `cancel`.

**A store per project, one read across them.** A project keeps its history under
its own root, because that is where its own `poieo runs` will look; the board
asks one question of all of them, and `MergedStore` is the seam. It merges on
the clock — inside one index the order is already the order runs finished, and
across two indexes nothing but the timestamp relates them. It is reads only:
a write would have to guess which project a run belongs to, and the runner
already knows. With one project there is nothing to merge and `daemon.store` is
that project's store.

**Two projects may not answer to the same name**, and the daemon refuses to
start when they do, naming both files and the `name:` key that fixes it. That is
the constraint that belongs here: a project's name is what tells it from another
one, on the board and in the address of every control route — and names collide
by default, since a project falls back to its folder's and a worktree is a
second folder called the same thing as the first.

Task names are free to repeat. Requiring *those* to be unique across projects,
which is what stood here first, refused the ordinary case: every project has a
`chores`. A task's identity is the pair, and the wire carries both.

`daemon.config` and `.tasks` still answer: `.config` for the first project, and
`.tasks` for every task whichever project it came from.

- **one `ProviderPool` per distinct binding file**, so clients are reused across
  tasks — and across projects, which is the point of keying on the file rather
  than on the project; **one container pool**, built only if some task asks for
  isolation
- `_hands_for()` assembles each task's `ToolContext` — its isolation setting, the
  shared container pool, and a `Postbox` if and only if its card took the `notes`
  toolset. A postbox reaches **that project's** cards and no others: a note is a
  line in another card's journal, and a journal is a file in one project's
  memory
- the web server, if a port was given, runs as a task on the same loop; the port
  is bound-checked up front so it fails at launch rather than after tasks start
- `SIGINT`/`SIGTERM` sets `cancel`, which drains in-flight runs; a second signal
  exits immediately. Windows has no `add_signal_handler`, and that is caught
- `asyncio.gather(..., return_exceptions=True)`: one task blowing up must not
  orphan the others or tear down pools they are still using
- on the way down, background tasks are awaited with a grace period and their
  failure is *logged*, not swallowed — a learning pass that blew up at 3am used
  to go down with the daemon without leaving a word behind

## Where the board listens

`127.0.0.1`, and `--host` is how that changes. *No auth* is a decision
resting on *nothing outside can reach it*, so the default is load-bearing.

So `web_exposure()` returns a sentence for every address that is not loopback,
logged at **warning** before the port is bound. It names what is reachable
rather than observing that the address changed: the board accepts a night's
work into the reader's own files, repoints a role at another model, and writes
a task that runs shell commands on this machine. None of it asks for a
password.

Opening it is a real thing to want — a phone is not this machine — and the flag
exists so that wanting it is written down rather than patched around. What it
is not is a default.

**Loopback is not by itself a fence, and the writes take one of their own.**
"Nothing outside can reach it" is true of a socket and false of a browser: any
page the reader has open can post to `http://127.0.0.1:8484` without them
knowing, and it is their own machine that delivers it. So a request that changes
something is refused when its `Origin` is not this page's own, or its `Host` is
not this machine — `SameOrigin`, argued in [web.md](web.md).

`_is_loopback` decides the second half, which is why it is here rather than
there: the daemon is what knows where it bound. On a **non-loopback `--host`
that half is off**, because a board reached by a LAN address or a machine name
cannot be told from a domain pointed at this one — the reader who passed the
flag has already spent that assumption, and the warning above is where it is
spent. A reverse proxy in front is the same shape and must forward the browser's
`Host` (`proxy_set_header Host $host;`), or the board loses every write.

None of this is auth, and it does not make `--host 0.0.0.0` any less of what the
paragraph above says it is. It is a fence against *the browser* being the way
in, which is the one thing loopback never covered.

## Cards that appear while it runs

`Daemon._watch_cards()` notices cards written after startup — a board that
can create tasks cannot ask for a restart. `serve()` gathers a fixed set of
runner coroutines, so the watcher starts late arrivals itself and waits them
out on the way down; a resident process may fail many ways, but never by
refusing to stop.

It **looks**, every `SCAN_SECONDS`, rather than being told. A card written by
hand has to start the same way a card written by the board does, and there is no
run to hang the reading on the way a graph's reread hangs on the next firing.
The cost is one directory listing.

The whole config is read again rather than the one new file, because a card
names the tasks it may tell and that roster is only known once the folder has
been read. What comes back goes through `load_tasks`, the same door startup came
through, so a card that would not have started here does not start now either —
and **a folder that will not load is a warning and no more**, the rule the
binding and the graph already follow. A card saved half-written must not take
down the tasks that have been running all night beside it.

**A task's identity is its filename**, so a card retitled at noon is the same
task, and the watcher does not read it as a second one.

**The scan runs in a thread.** `load_tasks` calls `check_isolation`, the only
preflight that reaches outside the process, and it shells out to docker with a
twenty-second timeout. On the event loop that would freeze the board, the timers
and every run in flight, every `SCAN_SECONDS`, for as long as the daemon is up.

**Nothing but shutdown ends the loop.** A raise anywhere in a scan is caught and
logged, because a loop that dies takes every future card with it and says so only
on the way down. The same complaint is logged once, not every five seconds.

**Two kinds of card are refused rather than half-given**, the rule the graph
reread follows. One asking for `isolation:` would run with no container keeper —
`self.containers` is built from the startup task set — and rebuild a throwaway
container per run while believing it was fenced. One taking the `notes` toolset
would be handed a postbox whose roster is a startup snapshot, so its own prompt
would name recipients the postbox then refuses. Both wait for a restart, and say
so.

**A daemon with nothing to run still waits**, as long as it has a folder to
watch — the first card the board writes needs somewhere to land.

Removal is not here yet: a card deleted while its run is in flight is a
different question, and this one only had to answer *appeared*.

## The learning loop

`learn: 1d` in the config starts a background loop, one per project that asked
for it, running a pass while **nothing else is running** — `_ready_to_learn()`
requires every runner to be `waiting`. Every runner anywhere, not just that
project's: learning would rather be late than contend, and another project's run
contends just as well as this one's. It is a double opt-in: the config key *and*
`memory/longterm.sqlite3`. Half an opt-in is how a feature dies quietly, so a
config that says `learn:` over a project with no memory logs a warning naming
both. See [memory.md](memory.md).

## A change that could not be recorded

A run's work is landed as one change, and there are three ways that does not
happen. `_open_change` can find no repository at all, or find one that will not
make a worktree; `_close_change` can be refused the commit. All three leave the
work done and the daemon running -- 3am is no time to stop -- and all three
leave `change = None`, which is not a quiet fact:

**`then:` conditions are written against `run.change`.** The improving-poieo
example hands off on `run.change and 'GREEN' in ...`, so a task whose commits
keep failing passes its own gate and **never hands over, forever**, while the
board shows a healthy green run that "changed nothing" -- which is exactly what
a run with nothing to do looks like.

So all three append `run_change_failed` to the run's own stream rather than
only logging. A line in the daemon's log is where nobody is looking; the run is
where somebody would. The two that happen before the run exists keep their
reason until there is a run to hang it on.

## A ceiling on the spend

A project may say what it is allowed to spend, as a rate:

```yaml
# poieo.yaml
spend:
  limit: 1.00
  over: 1h
```

**A rate rather than a total**, because a daemon has no end. "No more than a
dollar an hour" is a sentence somebody can mean; "no more than twenty dollars,
ever" is one they would have to keep resetting.

Checked where the daemon already decides whether to fire, and that placement is
the design. A run that has started is going to finish: a rate limit that killed
work halfway would waste exactly the money it was set to save. **Over budget is
a new reason not to fire, not a new way to stop.**

`RunStore.spent_since` reads the index backwards and stops at the first run
older than the window, so this costs a handful of lines read before each fire
rather than a walk through a log that grows all night.

**A run that never said what it cost counts as nothing.** For a local model that
is exactly right. For a paid endpoint that was not asked it understates, and a
limit set against it will let spend through — the answer to which is to ask the
endpoint (`usage: {include: true}`) or to declare the prices on the binding, not
to refuse to enforce anything. `docs/binding.md` covers both.

## Handoff

`examples/tasks/` ships one: **night-watch → mend → tell-me**, on the mock
binding, so the chain really fires and costs nothing. It is there because
nothing else demonstrated `then:` — the pair beside it talk through *notes*,
which is a different mechanism on purpose — and the board's central rule is
that an arrow crossing a border is a new run. A reader who opens the sample
project and finds no arrow anywhere never meets that rule.

`then:` on a task is the router's `branches`, one level up: `graph.Branch`
imported rather than redeclared, so `when` / `to` / `label` mean there what they
mean inside a graph. There is no `default` — a router needs one because a run has
to go somewhere, and a finished run does not. Falling off the end is what almost
every task does; a catch-all is a last branch reading `"true"`.

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

### What a branch can read

`handoff_scope(result)` is the `run` a condition tests, and it is also what the
next run reads as `input.sender` — one shape, so there is no second list to keep
in sync.

**Output aliases sit at the top level**, exactly as `RunContext.scope()` puts
them inside a run, so a condition on what a node said is written once and means
the same at both levels:

```yaml
# the graph                       # the card
output: {as: verdict}             then:
                                    - when: "verdict == 'GREEN'"
```

They are carried on `RunResult.aliases` and merged in by `_chosen()`, with
`setdefault` for the reason the graph's own scope uses it: a graph may alias
an output `run`, and a `then:` whose `run.status` had quietly become a node's
completion text is the worst bug this block can have.

`run.outputs` still answers by node id, and it is the spelling to reach for
when **the node may not have run at all**. A bare name that never arrived
raises, and an unreadable condition here is logged and skipped rather than
raised — so `run.outputs.get('gate', '')` is deliberate in
`examples/improving-poieo`, whose gate is not reached when the step before it
fails. `and` short-circuits, so `run.change and verdict == 'GREEN'` is safe
whenever the first half is false on exactly the runs the second half is missing
from.

### What is checked at load

`check_handoffs()` runs after the tasks folder is read (a card becomes a task
only at that point, and a handoff is entitled to name one):

- a target that is not a task is a **startup error**, and the message lists what
  there is
- a task pointing at itself is a **startup error** — `loop` and `carry_state` are
  what a task's own next run is for
- a disabled target **warns**; `enabled: false` is the off switch and may well be
  deliberate
- a cycle **warns** and still loads: review → fix → review is a legitimate
  feedback loop, and `MAX_CHAIN` is what bounds it
- handing off from a `loop` trigger **warns**, since everything downstream
  inherits that pace

### What happens when a run ends

`Daemon._hand_off()` is bound into every runner, and fires after the run —
**ahead of any stand-down**, because the run happened and what it says should
work next does not depend on whether this runner carries on. A task that pauses
itself on a third failure is exactly the one whose `broke` branch someone wanted.

1. `handoff_scope(result)` builds what a branch may test, and the run it starts
   reads the same object as `input.sender` — one shape, so there is no second
   list to keep in sync. It carries the same `usage` a router sees inside the
   run, so a guard on what a chain has cost is written once and reads the same
   at both levels — `MAX_CHAIN` bounds the hops, never what they spend. `change`
   is present-and-`None` rather than absent, because `when: "run.change"` is the
   commonest branch there is and it has to read false rather than raise.

   **Aliases are the one thing spelled differently at the two ends**, and it
   catches people out: `_chosen` hoists them to the top level for the condition,
   so a branch reads `when: "summary == 'GREEN'"` — but the object itself keeps
   them under `aliases`, so the *next* run's prompt reads
   `{{ input.sender.aliases.summary }}`. Writing the condition's spelling into
   the prompt fails the node with `no 'summary' here`, which is where
   `examples/tasks/mend.yaml` started.
2. `_chosen()` evaluates the branches router-style, first match wins. **A branch
   that will not evaluate is skipped, not fatal.** A router raises and takes the
   run with it, which is right while a run is still going; here the sender has
   already finished and landed its change, so there is nothing left to fail. The
   next branch gets its turn and the mistake is logged against the task that made
   it.
3. The target is woken by `hand()`, which — unlike `run_now()` — does not refuse
   mid-run. It **parks**, and the run loop finds it when the current run ends.

   A run that ended at a [`confirm` node](graph.md) is the one case where none
   of this happens yet: its status is `asking`, and the block is **deferred**
   rather than evaluated. The moment somebody answers, the run's status becomes
   `completed`, `run.answer` holds what they chose, and the branch is picked
   from there. Deferred and not skipped — otherwise the question would be
   theatre, with the chain carrying on underneath it.

The payload key is **`sender`, not `from`**: conditions and templates are parsed
as Python, where `from` is a keyword, so `input.from.change` would not even
parse. It is also what `tools/notes.py` already calls the other end of a message.
It is merged last, after the static input and the card's payload — what woke this
run is the most specific thing it knows.

### The four rules that bound it

- **One handoff waits, and the newest wins.** That is the interval trigger's rule
  one level up: a task that has fallen behind should work on the latest thing,
  not grind through a backlog it can never clear. Every displaced handoff is
  logged, because a loss nobody hears about is exactly what that rule would
  otherwise buy.
- **A paused target is not woken.** A handoff is not a reason to override a hold
  someone put on.
- **A chain stops after `MAX_CHAIN` (10) hops.** The same guard `max_steps` is
  inside a graph, for the same reason: a loop between tasks is legitimate,
  running forever is not. Depth rides on the `Handoff` so no task has to know how
  it was reached.
- **A disabled target is silently skipped.** It has no runner, and
  `check_handoffs()` already said so at load; saying it again per run would be
  noise.

`RunResult.trigger` records **what actually fired the run** (`fire.reason`),
not the schedule it may not have used — so a run-now on a cron task no longer
records the cron, and a handoff records `after <sender> (<label>)`. That is what
lets a run be traced back to the run that caused it.
