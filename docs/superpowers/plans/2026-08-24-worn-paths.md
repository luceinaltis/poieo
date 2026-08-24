# Worn Paths Implementation Plan (Plan I)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connections wear in with use — a pair of entries that helped together in work that succeeded arrives sooner and reaches further — provable by one test where the worn neighbor outranks its unworn sibling, one where a worn two-hop path arrives while an unworn one never does, and by every connections-slice test passing unchanged with an empty strength store.

**Architecture:** Three factors or nothing: cited (distinctive-token overlap with the run's own output — the declared proxy until attention instrumentation), succeeded, and decay-plus-fan-cap at every write. Strength lives in `.poieo/strength.json` (runtime emphasis, never meaning, never in markdown, never in the derived index — which stays deletable-loses-nothing). Reinforcement runs inside the learning pass (already the serialized single writer with exactly-once batches via the bookmark). Retrieval's neighbor pass becomes a spread: declared connections carry at full base value (zero strength ≡ the connections slice, byte for byte), wear adds carry within the first hop, and only wear carries to a second hop.

**Tech Stack:** Python 3.10, pytest + pytest-asyncio (asyncio_mode=auto). No new dependencies, no new index tables.

**Spec:** docs/superpowers/specs/2026-08-24-worn-paths-design.md

## Global Constraints

- **Backward-identical at zero strength.** No strength file (or an empty one) → the connections slice's behavior exactly; every Plan G test stays green untouched.
- **Strength modulates, never overrules:** direction rules stand (mentions both ways, leans forward, disagrees never), direct hits always outrank neighbors, all filters hold for everything reached, scan ≡ index.
- **Only declared pairs strengthen.** Co-presence alone earns nothing; failed runs earn nothing; failed passes earn nothing.
- **Runaway impossible by construction:** decay by age at read, per-entry fan cap at write.
- **Emphasis is never worth failing anything over:** corrupt/missing strength file degrades silently; a strength write failure never fails a pass.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **391 passed** at `ec1e2b5` with docker running; **361 passed, 30 skipped** with it stopped. Both must stay green.
- Comment style: sparse, explain constraints, not mechanics. Commits end with the model trailer, per CLAUDE.md.

## Vocabulary guard

A connection is **worn**; entries **helped together**. Banned beyond the earlier lists: *strength, weight, activation, spread, decay, reinforcement, Hebbian, citation, half-life, damping* (code and tests may use them; the interface may not — and this slice barely has an interface: wear is felt as ordering, not seen as a number).

---

### Task 1: the run records what it was shown

**Files:**
- Modify: `src/poieo/memory.py` (`_recall` returns entries, not bodies; `write_episode` records `shown`)
- Test: `tests/test_memory.py`

**Interfaces:**
- `_recall` returns the chosen `Fact`s; `read_memory` maps to bodies (no behavior change). `write_episode` recomputes the selection at record time and writes `"shown": [slugs]` — the same staleness the injection already accepts, and it must never fail the run (the episode's existing rule).

- [ ] **Step 1: Write the failing tests**

```python
def test_an_episode_records_what_the_run_was_shown(): ...
def test_a_memoryless_projects_episode_records_nothing_new(): ...
def test_a_shown_recording_failure_never_fails_the_run(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 364 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: a run's record says what the project had in mind`

---

### Task 2: the strength store

**Files:**
- Create: `src/poieo/strength.py`
- Test: `tests/test_strength.py`

**Interfaces:**
- `wear(project_dir, pairs) -> None` — reinforce undirected pairs by one, applying decay by age first and the per-entry fan cap after; atomic rewrite (tmp + replace); any failure logged, never raised.
- `wear_of(project_dir) -> dict[frozenset, float]` — current weights, decayed as of now; corrupt or missing file reads as empty; pairs naming entries that no longer exist are the caller's to ignore.
- Constants in one place: half-life, fan cap, base carry, second-hop threshold.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_reinforced_pair_carries_more_than_a_fresh_one(): ...
def test_an_untouched_weight_decays_toward_nothing(): ...
def test_the_fan_cap_holds_an_entrys_total_however_often_it_is_fed(): ...
def test_a_corrupt_file_reads_as_empty_and_heals_on_next_wear(): ...
def test_wear_never_raises(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 369 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: a strength store that decays and cannot run away`

---

### Task 3: the pass strengthens

**Files:**
- Modify: `src/poieo/learn.py`
- Test: `tests/test_learn.py`

**Interfaces:**
- After a successful pass, per completed run in the batch: cited = shown entries whose distinctive tokens overlap the run's summary+outputs by ≥ 2; every cited pair with a declared connection (any kind a retrieval would follow — mentions either way, leans-on; never disagrees) earns one reinforcement. Runs without `shown` (pre-slice episodes) strengthen nothing.
- Exactly-once rides the bookmark: a failed pass strengthens nothing, the reread earns it once.

- [ ] **Step 1: Write the failing tests**

```python
async def test_connected_cited_entries_in_a_completed_run_wear_in(): ...   # THE test
async def test_shown_but_uncited_earns_nothing(): ...
async def test_a_failed_run_earns_nothing(): ...
async def test_an_unconnected_cited_pair_earns_nothing(): ...
async def test_a_failed_pass_earns_nothing_and_the_reread_earns_once(): ...
async def test_a_disagreeing_pair_never_wears_in(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite**
- [ ] **Step 5: Commit** — `feat: the pass wears in the connections that helped`

---

### Task 4: retrieval spends the wear

**Files:**
- Modify: `src/poieo/memory.py` (the neighbor pass becomes the spread)
- Test: `tests/test_memory_search.py`

**Interfaces:**
- Chosen entries push carry across declared, direction-legal connections: base value 1 per declared connection (zero strength ≡ today), plus the pair's wear; a shared neighbor accumulates from every seed. Second hop carries wear alone — zero wear, no second hop. Neighbors ranked by carry, slug tie-break, after every direct hit; then the existing budget.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_worn_neighbor_outranks_its_unworn_sibling(): ...
def test_a_worn_two_hop_path_arrives(): ...
def test_an_unworn_second_hop_is_never_taken(): ...
def test_no_neighbor_outranks_a_direct_hit_however_worn(): ...
def test_a_worn_path_never_crosses_scope_or_resurrects_the_set_aside(): ...
def test_the_scan_and_the_index_still_agree(): ...
def test_an_empty_strength_store_changes_nothing(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite** — every Plan G test must pass unmodified
- [ ] **Step 5: Commit** — `feat: worn connections carry retrieval sooner and further`

---

### Task 5: document it and show it working

**Files:**
- Modify: `README.md` (one paragraph in the memory section)
- Test: by hand, per Step 3

- [ ] **Step 1: README** — connections wear in with use; what wears them (helped together, work that succeeded); that wear fades, lives outside git, and can be deleted without losing a word of meaning
- [ ] **Step 2: The whole suite, both ways** — docker running and stopped; paste both summary lines
- [ ] **Step 3: End to end by hand** — in the worked example: seed wear on one of two mentions from the same entry, watch `poieo memory` order flip; delete `.poieo/strength.json`, watch it revert; run the mock pass over a completed run citing two connected entries and watch the wear appear in the file
- [ ] **Step 4: Commit** — `docs: paths that wear in with use`

---

## Done means

- The three factors bind: shown-but-uncited, failed-run, and unconnected pairs all earn nothing; connected-cited-succeeded earns exactly once per successful pass.
- Wear reorders neighbors, extends reach one worn hop, and can never outrank direct evidence, cross a filter, or diverge the two lookup backends.
- Deleting `.poieo/strength.json` loses emphasis only, silently; the derived index remains deletable-loses-nothing; `git diff` of `memory/` never shows a number.
- With no wear anywhere, the memory behaves byte-for-byte as the connections slice left it.
