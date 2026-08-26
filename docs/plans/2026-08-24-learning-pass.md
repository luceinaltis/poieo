# Learning Pass Implementation Plan (Plan H)

**Goal:** The project reads the records its runs left behind and writes down what stays true — provable by one test where an entry written by a pass carries `source:` run ids stamped by the harness, and by a failed pass rereading the same records where a successful one never does.

**Architecture:** One new module, `src/poieo/learn.py`: an async `learn(project_dir, binding, pool)` that collects unread episode records oldest-first (capped), makes one completion under the `learner` binding role, validates the JSON proposal line by line, writes accepted entries (source stamped by the harness) and applies set-asides (one frontmatter line, body byte-identical), then appends one line to `.poieo/learning.jsonl` — which is also where the bookmark lives, moved only on success. The CLI command and the daemon's idle loop are thin callers. The pass never touches `constitution.md`, never deletes, never overwrites, and does not run at all without a `memory/` folder.

**Tech Stack:** Python 3.10, pytest + pytest-asyncio (asyncio_mode=auto), MockProvider scripted by role. No new dependencies.

**Spec:** docs/specs/2026-08-24-learning-pass-design.md

## Global Constraints

- **The harness writes, the model proposes.** `source:` is stamped from the records actually shown — a `from` naming anything else is cut to the batch, and an empty intersection stamps the whole batch.
- **Two verbs only:** write a new entry, set one aside. No page edits, no deletions, no overwrites (not even of the pass's own past work), no body edits.
- **The bookmark moves only on success**, and a capped pass moves it only as far as what was shown. Failure = reread, never skip.
- **One bad proposal drops alone**, named in the pass record; the rest land.
- **No `memory/` folder, no pass, anywhere** — the folder stays the project's one memory switch. A pass must never create it.
- **Learning yields to work**: the daemon's loop runs a pass only when every runner is waiting, and a failing pass never takes the daemon down.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **368 passed** at `3bf6075` with docker running; **338 passed, 30 skipped** with it stopped. Both must stay green.
- Comment style: sparse, explain constraints, not mechanics. Commits end with the model trailer, per CLAUDE.md.

## Vocabulary guard

The project **learns**; a pass **keeps** entries and **sets aside** others; the daemon learns **while nothing else is running**. Role `learner`, config key `learn`. Words that must not reach a prompt or CLI output, beyond the earlier lists: *compact, distill, pipeline, worker, proposal, cursor, batch, ingest*.

---

### Task 1: the pass

**Files:**
- Create: `src/poieo/learn.py`
- Test: `tests/test_learn.py`

**Interfaces:**
- `async learn(project_dir, binding, pool) -> Pass | None` — `None` when there is no `memory/` folder or nothing unread; otherwise a record of what happened (read/kept/set aside/dropped/error), which is also what lands in `.poieo/learning.jsonl`.
- The prompt carries the page, the kept entries (budgeted), and the unread records oldest-first (capped per pass). It says plainly that an empty answer is the right answer most nights.
- The completion is one `provider.complete(...)` under role `learner` — no retry machinery of its own; the next pass is the retry. JSON is accepted with or without a code fence.
- Validation per proposal: plain slug, no collision with disk or the same pass, typed links resolve (counting entries accepted this pass), set-aside targets exist and `because` resolves likewise.

**Why the library is first and alone.** Everything dangerous is here. The CLI and the daemon must be able to trust `learn()` completely, so every refusal and every stamp is pinned before either caller exists.

- [x] **Step 1: Write the failing tests**

```python
async def test_an_entry_learned_carries_the_runs_that_taught_it(): ...   # THE test
async def test_a_forged_from_is_cut_to_the_records_actually_shown(): ...
async def test_a_failed_pass_rereads_and_a_passed_one_does_not(): ...
async def test_a_capped_pass_drains_across_passes_and_drops_nothing(): ...
async def test_a_bad_slug_is_dropped_and_the_rest_still_land(): ...
async def test_a_colliding_slug_never_overwrites(): ...
async def test_a_dangling_link_in_a_proposal_is_dropped(): ...
async def test_a_set_aside_changes_one_line_and_keeps_the_body(): ...
async def test_a_set_aside_may_point_at_an_entry_kept_this_pass(): ...
async def test_a_set_aside_of_a_missing_entry_is_dropped(): ...
async def test_an_empty_proposal_is_a_success(): ...
async def test_non_json_fails_the_pass_and_moves_nothing(): ...
async def test_the_page_is_never_written(): ...
async def test_a_memoryless_project_never_gains_a_folder(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 352 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: a pass reads the run records and writes down what stays true`

---

### Task 2: `poieo learn`

**Files:**
- Modify: `src/poieo/cli.py`
- Test: `tests/test_cli_memory.py`

**Interfaces:**
- `poieo learn <folder-or-card> [-b binding]` — one pass, now. A card supplies its project and (absent `-b`) its binding, exactly as `run` resolves one. Prints what was kept and set aside, or that there was nothing to read, or how the pass failed — always in the product's voice.
- A memoryless project: says how to start one, exit 0 (the `poieo memory` precedent).

- [x] **Step 1: Write the failing tests**

```python
def test_learn_runs_one_pass_and_says_what_it_kept(): ...
def test_learn_says_when_there_is_nothing_to_read(): ...
def test_learn_without_memory_says_how_to_start_and_exits_zero(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 355 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: poieo learn runs one learning pass by hand`

---

### Task 3: the daemon learns while nothing else is running

**Files:**
- Modify: `src/poieo/daemon/config.py` (`learn: str | None` on DaemonConfig, duration-parsed at load), `src/poieo/daemon/service.py` (the loop, beside the web task)
- Test: `tests/test_daemon.py`

**Interfaces:**
- `learn: 1d` — a duration, validated at load (fail at launch). Absent means off; learning stays double opt-in (the folder and the key).
- The loop: cancellable sleep (`_sleep_or_cancel`), then one pass only if every runner is waiting and the config names a tasks folder with a `memory/`; any exception is logged and the loop lives on — the box-sweep rule, "tidying is never worth refusing to start over", applied continuously.
- One pass at a time is structural: one loop, no concurrency.

- [x] **Step 1: Write the failing tests**

```python
def test_a_learn_interval_parses_and_a_bad_one_fails_at_load(): ...
def test_learning_needs_the_daemon_default_binding(): ...   # added: fail at launch
def test_an_unconfigured_daemon_never_learns(): ...
def test_a_daemon_without_a_memory_folder_never_learns(): ...
def test_a_busy_daemon_waits_its_turn(): ...
def test_a_failing_pass_never_takes_the_daemon_down(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 361 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: the daemon learns from the night while nothing else is running`

---

### Task 4: document it and show it working

**Files:**
- Modify: `README.md` (the memory section learns), `examples/bindings/mock.yaml` (a scripted `learner` answer)
- Test: by hand, per Step 4

- [x] **Step 1: The scripted learner** — mock.yaml gains a `learner` response proposing one entry (empty `from`, so the harness stamps the batch); the `"*"` fallback stays non-JSON, which is itself the failure path demo
- [x] **Step 2: README** — the memory section gains the learning paragraph: records pile up, `poieo learn` or `learn: 1d` turns them into entries, everything traceable, nothing deleted
- [x] **Step 3: The whole suite, both ways** — docker running: 391 passed in 18.25s; docker stopped: 361 passed, 30 skipped in 7.19s
- [x] **Step 4: End to end by hand** — done 2026-08-24: the entry landed with `source: ["20260824T123915-f0515c68"]`, the second pass said nothing new, `poieo memory` counted it, `.poieo/learning.jsonl` recorded the pass; artifacts cleaned before commit
- [x] **Step 5: Commit** — `docs: the project learns from what its runs leave behind`

---

## Done means

- An entry a pass wrote can be walked: `source:` → episode → run log, and the ids are the harness's, not the model's.
- A failed pass rereads; a successful one never rereads; a capped pass drains without loss; an empty answer is a recorded success.
- No pass, ever: touches the page, deletes anything, overwrites anything, edits a body, or creates a `memory/` folder.
- The daemon learns only when configured, only when idle, and survives every pass failure.
- `.poieo/learning.jsonl` answers "what did learning do last night?" line by line.
