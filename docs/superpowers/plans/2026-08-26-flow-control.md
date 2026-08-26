# Flow Control — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-08-26-flow-control-design.md`
**Branches:** `flow-control`, `flow-control-api`, `flow-control-board` (one PR each)

Gate before every merge:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio
npm test --workspace web-ui        # Task 3 only; run mode, never watch
```

---

## Task 1: the runner learns to be told

`daemon/service.py` `FlowRunner`:

- A per-runner control channel (asyncio, same loop as the web server) and
  three methods: `pause()`, `resume()`, `run_now()`. `run_now` answers
  whether it fired or was refused (a run in flight).
- `run()` races the trigger's next fire against the channel instead of
  iterating the generator directly. Trigger classes untouched.
- Paused: stop consuming the trigger; hold at most one due fire unconsumed;
  discard it on resume (the next fire is the next scheduled one). A `loop`
  trigger must sit suspended through a pause, not spin.
- Manual fires carry `reason="run now"` and do not advance the trigger's
  iteration count.
- The self-pause parks in this same paused state instead of `break`ing; its
  journal line becomes "resume it from the board, or restart the daemon."
- `cancel` ends a paused or holding runner promptly.

Tests:

- [x] pausing a waiting flow skips the fire that comes due; resume rearms and
      the next scheduled fire runs (interval trigger: the grid, not a make-up).
- [x] a paused `loop`-trigger flow does not spin (no runs, bounded wall-clock).
- [x] `run_now` on a waiting `manual`-trigger flow runs it once — the first
      way a manual flow has ever run inside the daemon.
- [x] `run_now` on a paused flow runs once; the flow is still paused after.
- [x] `run_now` while a run is in flight is refused and no second run starts.
- [x] a flow that paused itself after 3 identical failures resumes via
      `resume()` and its failure counter starts over.
- [x] shutdown while paused, and while holding a due fire, exits cleanly.

PR `feat: a flow can be paused, resumed, and run right now`.

---

## Task 2: the API speaks the three verbs

`web/server.py`:

- `POST /api/flows/{flow}/pause`, `/resume`, `/run` calling the runner's
  methods. 404 unknown flow; pause/resume idempotent 200 answering the
  resulting status; `/run` 409 with the current run id when mid-run.
- The module header's standing rule rewritten as the spec words it: accept
  and discard remain the only routes that may touch the user's files; the
  control routes touch the daemon's runtime state and nothing else.

Tests:

- [x] each verb against a live test daemon changes what `/api/flows` reports.
- [x] pause twice → 200 both times; resume a waiting flow → 200.
- [x] `/run` during a run → 409 naming the run; unknown flow → 404 on all three.

PR `feat: pause, resume and run-now land on the web API`.

---

## Task 3: the board gets the verbs

`web-ui/`:

- `api.ts`: `pause(flow)`, `resume(flow)`, `runNow(flow)`; the header comment
  about "the only two POSTs" updated with the same two-fences wording as the
  server.
- Each flow card: a pause/resume toggle driven by the status it already
  shows, and a run-now control disabled while `running`. Refusals (409) are
  shown, not swallowed.
- Rebuild `src/poieo/web/static/` (checked in deliberately).

Tests:

- [x] vitest: the toggle sends pause when waiting and resume when paused; the
      buttons reflect a 409 refusal instead of pretending.
- [x] vitest: run-now disabled while running.

PR `feat: the board can hold a task, wake it, and run it right now`.
