# Memory Upkeep Implementation Plan (Plan J)

**Goal:** Rot is noticed, the second look actually happens, and the long-set-aside step out of the way — nothing deleted — provable by a gone anchor earning its report line, the pass prompt carrying the doubt, and an old unreferenced set-aside moving whole to `memory/attic/` while a referenced one stays.

**Architecture:** No new state anywhere. Rot (anchor target gone, or changed after the entry's own mtime) is computed at read time beside the existing second-look logic. The pass prompt gains the doubt section; the recheck uses the pass's existing verbs. The attic move happens on a successful pass: set-aside entries older than the grace, not named by any typed reference, `git mv`-style file move to `memory/attic/` (content untouched). The pass answer's optional `page` line is recorded in the pass log and surfaced by `poieo memory`; it never touches `memory/`.

**Tech Stack:** Python 3.10, pytest + pytest-asyncio. No new dependencies.

**Spec:** docs/specs/2026-08-24-memory-upkeep-design.md

## Global Constraints

- **Nothing is deleted, still.** The attic is a move; content byte-identical; collisions skip; failures leave the entry in place.
- **Referenced entries never move**: any `depends_on`/`contradicts`/`superseded_by` naming an entry holds it in `facts/` however old — the load-time cross-check must keep passing.
- **The page is never written by a machine**, not even to hold a suggestion.
- **Quiet when there is nothing to say**: no doubts, nothing attic-ready, no suggestion → prompt, report, and pass log byte-identical to the prior slices.
- **A failed pass changes nothing**, as ever.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **412 passed** at `3ae1b95` with docker running; **382 passed, 30 skipped** with it stopped. Both must stay green.
- Comment style: sparse. Commits end with the model trailer, per CLAUDE.md.

## Vocabulary guard

An entry is **gone** or **changed after it was written**; old set-asides **move to the attic**; the pass **suggests**. Banned beyond earlier lists: *rot, revalidation, stale, grace period, tombstone, archive, GC, lifecycle*.

---

### Task 1: the report sees rot

**Files:**
- Modify: `src/poieo/memory.py` (`memory_report` second-look reasons), `src/poieo/cli.py` (print reasons)
- Test: `tests/test_cli_memory.py`

**Interfaces:**
- `second_look` entries become `(slug, reason)` sentences: the stale lean (existing), an anchor path that does not exist ("names X, which is gone"), an anchor target modified after the entry file ("names X, which changed after it was written"). Unreadable stat = present, never doubt.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_gone_anchor_earns_a_second_look(): ...
def test_a_target_changed_after_the_entry_earns_a_second_look(): ...
def test_touching_the_entry_clears_the_changed_after_line(): ...
def test_a_healthy_memory_reports_no_doubts(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 386 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: the report notices when the code moved under an entry`

---

### Task 2: the pass rechecks, and may suggest a page line

**Files:**
- Modify: `src/poieo/learn.py` (prompt section; `page` in the answer; `Pass.page`), `src/poieo/memory.py` (share the doubt computation), `src/poieo/cli.py` (`poieo memory` shows the last suggestion)
- Test: `tests/test_learn.py`, `tests/test_cli_memory.py`

**Interfaces:**
- The pass prompt gains "Worth a second look:" with reasons, only when non-empty; the recheck is the existing `set_aside` verb, nothing new to validate.
- The answer's optional `"page"` (one line, string) lands in `Pass.page` and the pass log; `poieo memory` prints `the last pass suggests: …` from the most recent successful pass that carried one, nothing when the latest successful pass carried none.

- [ ] **Step 1: Write the failing tests**

```python
async def test_the_pass_is_shown_what_is_doubtful(): ...
async def test_a_doubted_entry_can_be_set_aside_by_the_pass(): ...
async def test_a_page_suggestion_is_recorded_never_written(): ...
def test_memory_shows_the_last_suggestion_and_only_the_last(): ...
async def test_a_quiet_night_leaves_the_prompt_as_it_was(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 391 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: the pass rechecks what is doubtful and may suggest a page line`

---

### Task 3: the attic

**Files:**
- Modify: `src/poieo/learn.py` (the move, on success), `src/poieo/memory.py` (a helper naming who is referenced)
- Test: `tests/test_learn.py`

**Interfaces:**
- After a successful pass: set-aside entries whose file mtime is older than the grace (90 days, one constant) and which no typed reference names, move whole to `memory/attic/` (created on first need). Collision → skip and log; failure → entry stays; either way the pass's other work stands.

- [ ] **Step 1: Write the failing tests**

```python
async def test_an_old_unreferenced_set_aside_moves_to_the_attic_whole(): ...
async def test_a_referenced_set_aside_stays_however_old(): ...
async def test_a_fresh_set_aside_stays(): ...
async def test_attic_entries_reach_no_load_no_report_no_prompt(): ...
async def test_an_attic_collision_is_skipped_and_said(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 396 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: long set-aside entries move to the attic, never the void`

---

### Task 4: document it and show it working

**Files:**
- Modify: `README.md` (a short upkeep paragraph in the memory section)
- Test: by hand, per Step 2

- [x] **Step 1: README** — the memory keeps itself honest: doubts are shown and rechecked, old set-asides move to the attic, the page can be suggested at but only you edit it
- [x] **Step 2: End to end by hand** — done 2026-08-24: a gone anchor printed `second look  sources-note names notebook/sources.md, which is gone`; a 120-day set-aside moved to `memory/attic/` on one mock pass (`"to_attic": ["ancient-cap"]` in the pass log); moving the file back restored the counts; artifacts cleaned before commit
- [x] **Step 3: The whole suite, both ways** — docker running: 426 passed in 19.26s; docker stopped: 396 passed, 30 skipped in 7.86s
- [x] **Step 4: Commit** — `docs: a memory that keeps itself honest`

---

## Done means

- A gone or changed-under anchor is one visible sentence, cleared by touching the entry after looking.
- The pass sees every doubt and can retire a doubted entry with its existing verbs; a failed pass changes nothing.
- The attic holds old, unreferenced set-asides whole; referenced or fresh ones stay; nothing under `memory/` is ever deleted or content-rewritten by the move.
- A page suggestion reaches the log and the report, never a file under `memory/`.
- With nothing doubtful and nothing old, every surface is byte-identical to the association slice.
