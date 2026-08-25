# Failure Causes — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-08-25-failure-causes-design.md`
**Branches:** `failure-causes`, then `flow-self-pause` (one PR each)

Gate before every merge:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio
```

---

## Task 1: the cause — classified once, shown everywhere

- `errors.py`: `Cause` (slug / said / fix) and `explain_failure(exc) -> Cause | None`,
  walking the exception chain, matching the spec's table. Unmatched → None.
- `runtime/executor.py`: both catch branches classify; `RunResult` gains
  `cause` (dict | None); `summary()` includes it when set; `run_failed` /
  `run_aborted` events carry it.
- `cli.py` run: under the error line, `cause` and `try` lines when classified.
- `task.py` `record_run`: the journal `failed` line becomes
  `<said> -- <fix>` when classified; raw error unchanged when not.

Tests:

- [ ] unit: one classification test per slug in the table, built from the
      real exception shapes (NodeError wrapping ProviderError, etc.); an
      unmatched error returns None.
- [ ] integration: a graph whose node demands JSON from a mock that answers
      prose fails with `bad_output`; `poieo run` output shows `cause` and
      `try`; the summary row carries the cause.
- [ ] a failed task run leaves a journal line with the sentence, not the
      exception repr.

PR `feat: failed runs say why, in words, everywhere the run goes`.

---

## Task 2: the pause — three identical failures and the flow stops shouting

- `daemon/service.py` `FlowRunner`: consecutive-failure counter keyed by
  cause slug (or raw error when unclassified); completed run resets it; at 3
  the runner sets `status = "paused"`, logs the sentence, writes a journal
  line for task-backed flows, and leaves the trigger loop.
- `on_error: stop` behaviour unchanged; `--once` runs are naturally exempt
  (max one iteration).

Tests:

- [ ] a looping flow failing identically pauses after exactly 3 runs; status
      is `paused`; a fourth run never fires.
- [ ] alternating failure causes never pause it (the counter resets on a
      different key).
- [ ] a success between failures resets the counter.
- [ ] the task journal records why it paused.

PR `feat: a flow that fails the same way three times pauses itself and says so`.
