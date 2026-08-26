# Flow Control Design

**Date:** 2026-08-26
**Status:** Approved for planning
**Relates to:** DESIGN.md roadmap item 6 (web control plane) — this is its first
slice. Closes the loose end `2026-08-25-failure-causes-design.md` left open:
*"resuming is deliberately manual in this slice: restarting the daemon rearms
the flow. The web control plane's resume button lands with the rest of its
mutations, later."* This is later.

## Goal

The board can watch (observation) and judge (the review), but it cannot steer.
Three gaps, in the order they hurt:

- A flow that **paused itself** after three identical failures can only be
  revived by restarting the daemon — which also restarts every flow that was
  fine. The journal literally tells the user to do this.
- A **`manual`-trigger flow cannot be run at all** inside the daemon. The
  trigger's own docstring says "the flow only runs when something asks it to",
  and nothing can ask.
- There is no way to **hold a flow** while you edit the folder it works in, or
  to **try a card right now** instead of waiting for its 2am cron.

Three verbs fix all of it: **pause**, **resume**, **run now**. Per flow, from
the board. This is the "Control — pause/resume, run once right now" line in
DESIGN.md's target experience.

## 1. The verbs

**Pause** stops the flow's schedule. It takes effect between runs — an
in-flight run finishes and lands its change, exactly as shutdown already
promises. Fires that come due while paused are **skipped, not queued**: pausing
a nightly task over the weekend means two quiet nights, not three runs
back-to-back on Monday.

**Resume** rearms the schedule. The next fire is the next scheduled one — the
interval trigger's grid and the cron's calendar already work this way, and
resume inherits it. Resuming a flow that paused itself works the same as
resuming one the user paused; the failure counter starts over.

**Run now** is one fire, immediately, outside the schedule. It does not
advance the trigger's iteration count and does not move the interval grid.
It is refused while a run is in flight — iterations never overlap, the same
resume-after-run property the triggers guarantee. On a paused flow it runs
once and leaves the flow paused: exactly what is wanted when probing whether
the cause of a self-pause has cleared.

A pause lives and dies with the daemon. Turning a flow off *permanently* is
already a file — `enabled: false` — and stays one. That is principle 4's
division, not an exception to it: a lasting decision belongs in a file that
versions with git; a moment's "hold on" belongs to the resident process, and
a daemon restart returning every enabled flow to armed is the same clean
slate it is today.

## 2. The runner

`FlowRunner.run` today has one voice in its ear: `async for fire in
trigger.fires(cancel)`. It becomes two voices raced — the trigger's next fire
and a per-runner control channel. The trigger generators do not change at all;
their resume-after-run property, the interval grid, and the cron calendar are
untouched. What changes is who is listening.

While paused, the runner stops consuming the trigger. At most one already-due
fire is held unconsumed (the generator sits suspended at its yield, so nothing
spins — a `loop` trigger with no cooldown must not busy-wait through a pause)
and is discarded on resume in favour of the next scheduled one.

The self-pause from `failure-causes` folds into this state instead of keeping
its own: where it now `break`s out of the loop — ending the coroutine, which
is why only a restart could revive it — it parks in paused and waits. The
journal line drops "restart the daemon" for "resume it from the board, or
restart the daemon."

Shutdown outranks everything: `cancel` still ends a paused runner as promptly
as a waiting one.

## 3. The API and the board

Three routes beside accept and discard:

```
POST /api/flows/{flow}/pause    -> 200 {"status": "paused"}
POST /api/flows/{flow}/resume   -> 200 {"status": "waiting"}
POST /api/flows/{flow}/run      -> 200 {"status": "running"}
```

Unknown flow: 404. Pausing a paused flow and resuming a waiting one are
idempotent 200s — the answer is the state, not a scolding. `run` on a flow
mid-run: 409, with the current run's id in the body.

`web/server.py` opens with a standing rule: accept and discard are the only
routes that write anything, "if you are adding a third, stop." The rule is
rewritten, not broken, because what it actually guards is the moment the
user's own files change. That guard stands: accept and discard remain the
only routes that can touch the user's files. The control routes touch the
daemon's runtime state and nothing else, and the header will say exactly
that — two kinds of writes, one fence each.

The board wires the verbs to what it already shows: each card gets
pause/resume (one toggle, driven by the status field the flows endpoint
already serves) and run-now, disabled while the card is `running`.

## Out of scope

- **Task card CRUD and runtime flow add/remove** — the rest of roadmap item
  6, its own design. These verbs deliberately touch only flows the daemon
  already loaded.
- **CLI verbs** (`poieo pause <flow>`) — the CLI has no channel to a running
  daemon today, and the board is the target surface. If an agent operator
  needs control, the API answers with JSON already.
- **Persisting pause across restarts** — `enabled: false` is the durable off
  switch; see above.
- **A trigger whose `max_iterations` ran out** stays finished. Run-now for
  completed schedules can arrive if someone misses it.
- **Auto-resume when a failure cause clears** — unchanged from the
  failure-causes design: needs probe machinery on a schedule, design it on
  real demand.
