# Project Memory Implementation Plan (Plan F)

**Goal:** A project keeps what it has learned, every task reads it before working, and anything remembered can be traced to the run that taught it — provable by one test where a project without a `memory/` folder produces prompts byte-identical to today, and one walk where an injected entry is followed back to the run that taught it.

**Architecture:** Truth in markdown under git (`memory/constitution.md` + `memory/facts/*.md`), machine layer under the gitignored `.poieo/` (one episode file per run, one derived index that rebuilds from the facts). One new module, `src/poieo/memory.py`, owns the format, the retrieval, and the composed block; the rest of the codebase gains one gated section in the generated system prompt, one guarded line at each of the two input sites, one call in `record_run`, and one read-only CLI command.

**Tech Stack:** Python 3.10, stdlib sqlite3 (FTS5 when the build has it, plain scan when not), pytest + pytest-asyncio (asyncio_mode=auto).

**Spec:** docs/specs/2026-08-24-project-memory-design.md

## Global Constraints

- **Zero configuration is the invariant.** No `memory/` folder → no template block, no payload key, prompts byte-identical to a build without this feature, on the daemon path and the CLI path both. Not an empty section — silence.
- **Truth and derivation never share a layer.** Nothing machine-derived is ever written inside `memory/`; nothing under `.poieo/` is ever the only copy of a meaning. Deleting `.poieo/memory.sqlite3` must lose nothing.
- **Demote before delete.** No code path in this plan deletes a fact. `superseded_by` set → excluded from retrieval, file intact.
- **Episodes are append-only and harness-written.** No agent-facing memory tool exists in this slice. An existing episode file is never rewritten.
- **Memory never kills work.** Any memory failure at run time (unreadable page, failed episode write, broken index) is logged and the run proceeds or its result stands — the journal's rule.
- **The two input sites move together.** Daemon `read_input` and CLI `_task_payload` gain the same guarded line; a test covers each, because that duplication is where this feature would silently half-work.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **287 passed, 30 skipped** at `38d1973` with docker stopped. Must stay green (and with docker running, nothing new may skip or fail).
- CLI one-shot runs already call `record_run` (`078adce`) — Task 1 relies on that seam catching both runners.
- Comment style: sparse, explain constraints, not mechanics. Commits end with the model trailer, per CLAUDE.md.

## Vocabulary guard

The prompt says **"What this project always requires:"** and **"What earlier work here has learned:"**. A wrong entry is *set aside*, not deleted. Words that must not reach a prompt, a card, or CLI output: *tier, fact, episode, retrieval, index, search, embedding, compaction, distill, anchor, namespace, scope, frontmatter, SQLite, FTS, store, recall, knowledge base*. (Tests and code may use them; the interface may not.)

---

### Task 1: every piece of work leaves a full record

**Files:**
- Create: `src/poieo/memory.py` (the episode writer)
- Modify: `src/poieo/task.py` (`record_run` calls it)
- Test: `tests/test_memory.py`

**Interfaces:**
- `write_episode(task, result) -> Path | None` — one JSON file per run at `task.dir/.poieo/episodes/<run_id>.json`: run id, task slug, name, resolved folder, status, error, iteration, steps, path, usage, started/finished — straight off `RunResult` — plus the closing summary and per-node outputs **unclipped** (the event stream clips at 400 chars; this is the copy that does not).
- Called from `record_run`, which both runners already pass through — so neither runner changes and no signature widens. `RunResult` has no `trigger` field; the episode omits it rather than threading one.

**Why this task is first.** Episodes are the raw material every later slice distills from, and they are useful alone: an auditable, unclipped result per run, even before anything reads them. Recording must not wait for retrieval to exist — every run that passes unrecorded is a lesson lost.

**Anchoring.** Episodes land under `task.dir/.poieo` always — not under the run-log store, which a daemon config may point elsewhere. One project, one memory; the run id joins the two wherever the run log lives.

- [x] **Step 1: Write the failing tests**

```python
def test_a_completed_run_leaves_an_episode(): ...
def test_a_failed_run_leaves_an_episode_too(): ...
def test_the_episode_summary_is_not_clipped(): ...        # the reason it exists
def test_the_episode_joins_the_run_log_by_run_id(): ...
def test_a_graph_without_a_task_leaves_no_episode(): ...
def test_an_existing_episode_is_never_rewritten(): ...
def test_an_unwritable_episode_is_logged_and_the_result_stands(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 294 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: every task run leaves a full record behind`

---

### Task 2: the page every run reads

**Files:**
- Modify: `src/poieo/memory.py` (page format, fact frontmatter parsing, `read_memory`)
- Modify: `src/poieo/task.py` (`system_block` gains a gated section)
- Modify: `src/poieo/daemon/config.py` (`read_input`), `src/poieo/cli.py` (`_task_payload`)
- Test: `tests/test_memory.py`, `tests/test_task.py`

**Interfaces:**
- `read_memory(project_dir, task) -> str | None` — `None` when there is nothing (no folder, empty folder); otherwise the composed block: constitution first and whole, under the interface headers. In this task the block carries the constitution only; facts are parsed and validated but not yet retrieved — retrieval is Task 3, and stacking it here would bury the byte-identity work under ranking questions.
- `system_block` gains a section containing `{{ input.memory }}`, gated on `(task.dir / "memory").is_dir()` at graph-build time — the `_roster_block` pattern. Both input sites gain the guarded mirror of the journal line: `payload["memory"] = ...` only when there is something to carry.
- Malformed fact frontmatter fails at load naming the file (fail at launch, not at 3am). An oversized constitution warns and loads whole — the page is the user's to trim.

**Why the gate is filesystem presence.** The journal's gate is "being a task"; memory's is "the project chose to have one." A folder is the whole opt-in, which is what minimal configuration promises. Consequence, accepted and stated: a `memory/` created while the daemon is resident appears on the next load, like a new task file; *edits* to an existing memory are re-read every run, like the journal.

- [x] **Step 1: Write the failing tests**

```python
def test_no_memory_folder_means_prompts_identical_to_today(): ...   # THE test, both paths
def test_the_constitution_reaches_the_prompt_on_the_daemon_path(): ...
def test_the_constitution_reaches_the_prompt_on_the_cli_path(): ...
def test_an_edit_takes_effect_next_run_without_reload(): ...
def test_a_malformed_fact_fails_at_load_naming_the_file(): ...
def test_an_oversized_page_warns_and_still_loads_whole(): ...
def test_an_empty_memory_folder_behaves_as_absent(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 302 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: a project keeps a page every task reads before working`

---

### Task 3: remembering the right things

**Files:**
- Modify: `src/poieo/memory.py` (the index, the capability probe, ranking, the budget)
- Test: `tests/test_memory_search.py`

**Interfaces:**
- The index lives at `task.dir/.poieo/memory.sqlite3`, built from `memory/facts/`, freshness checked by a fingerprint of names+mtimes; missing, stale, or corrupt → rebuilt silently. Derived means never asked about.
- FTS5 is probed once per process by creating an in-memory FTS5 table (the `docker_available` pattern). Absent → a plain scan over the same fact set behind the same function signature: same results, slower, said once in the log, never an error.
- The seed is what the task is: name, prompt, folder. A fact whose anchor paths overlap the task's folder ranks above a merely-similar one. The scope filter keeps `global`, the task's slug, and path prefixes covering the card's `folder`; everything else stays out. Superseded facts never surface.
- The budget is measured in characters (no tokenizer dependency), cuts on whole-fact boundaries, best first, and never touches the constitution.

**Why ranking and fallback are one task.** The fallback is only honest if it is exercised against the same expectations as FTS5 — one test suite, two backends, same answers. Splitting them would let the fallback rot into a different feature.

- [x] **Step 1: Write the failing tests**

```python
def test_a_relevant_entry_reaches_the_block(): ...
def test_the_fallback_returns_the_same_entries_as_fts(): ...   # forced fallback
def test_a_superseded_entry_never_surfaces(): ...
def test_scope_admits_global_and_own_and_excludes_foreign(): ...
def test_an_anchored_entry_outranks_a_merely_similar_one(): ...
def test_an_anchored_entry_arrives_even_without_a_shared_word(): ...   # added: equivalence hole
def test_the_budget_cuts_whole_entries_and_spares_the_page(): ...
def test_a_deleted_index_is_rebuilt_silently(): ...
def test_nothing_is_ever_written_inside_the_memory_folder(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 311 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: a task is shown what earlier work here has learned`

---

### Task 4: seeing what it remembers

**Files:**
- Modify: `src/poieo/cli.py`
- Test: `tests/test_cli_memory.py`

**Interfaces:**
- `poieo memory <folder-or-card>` — one read-only command, no subcommand group. For a folder: the page's size against its budget, how many entries are active and how many set aside, and which lookup this machine runs (the friendly word for the backend). For a card: additionally, the exact block that task would be shown on its next run.
- Rejected: `memory add` (authoring belongs to the editor and git), `memory rebuild` (rebuilding is automatic — a command for it would imply it can be needed).

**Why this ships in the first slice.** Measurement from day one is a design decision, not a nicety: "what would this task see, and why?" must be answerable before anyone trusts the memory, and the dry-run *is* the debugging story for a wrong retrieval.

- [x] **Step 1: Write the failing tests**

```python
def test_memory_reports_page_size_counts_and_lookup(): ...
def test_memory_with_a_card_prints_exactly_what_the_run_would_see(): ...
def test_memory_is_read_only(): ...                        # no file mutated, no index created
def test_a_project_without_memory_says_so_plainly_and_exits_zero(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 315 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: poieo memory shows what a project remembers and what a task would see`

---

### Task 5: document it and show it working

**Files:**
- Modify: `README.md`
- Modify: `DESIGN.md` (capability layers and roadmap — status only; the wording landed with the spec)
- Create: an example project under `examples/` — a constitution, three entries (one global, one scoped, one set aside), two cards on the mock binding

- [x] **Step 1: The example** — `examples/remembering/`: two cards, one memory, one entry scoped, one global, one set aside

- [x] **Step 2: README**

Extend the journal section — the placement is the argument: journal for lately, memory for always. Say the folder is the opt-in, the page is always in front of every task, entries are chosen per task, a wrong entry is set aside rather than deleted, and every entry can be traced to the work that taught it.

- [x] **Step 3: DESIGN.md**

The Memory capability-layer row and roadmap entry change status. Change the status, not the argument; keep the file under 500 lines and at the logic level.

- [x] **Step 4: The whole suite, both ways** — docker running: 346 passed in 18.76s; docker stopped: 316 passed, 30 skipped in 6.88s

- [x] **Step 5: End to end by hand**

Run a card; confirm the constitution and the scoped entry appear in its prompt and the foreign and set-aside ones do not. Edit the page, run again, see the edit. Delete `.poieo/memory.sqlite3`, run again, see nothing change. Follow one entry's `source` to an episode and the episode to its run log — the traceability walk. Then delete `memory/` and confirm the prompt reverts to today's, byte for byte. *(Done 2026-08-24; the walk also surfaced that editor comments in the page reached the prompt — fixed in this task with `test_editor_notes_in_the_page_never_reach_the_prompt`.)*

- [x] **Step 6: Commit** — `docs: a project remembers what it has learned`

---

## Done means

- A project without `memory/` produces prompts byte-identical to today, on both paths — the feature is invisible until opted into.
- Every task run leaves an unclipped record joined to its run log; a failed run too; a failed write never fails a run.
- What a task is shown is chosen by what it is and where it works, fits a budget cut on whole entries, and never includes what was set aside.
- The same questions get the same answers with and without FTS5.
- `poieo memory` answers "what would this task see?" without touching anything.
- Nothing machine-written sits inside `memory/`; deleting `.poieo/memory.sqlite3` loses nothing; `git diff` of a memory is always a diff of meaning.
