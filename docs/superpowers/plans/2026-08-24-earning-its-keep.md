# Earning Its Keep Implementation Plan (Plan L)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `poieo memory` answers "is the memory earning its keep" from the run records alone — provable by the used-judgment being the wear system's shared function (not a twin), by an entry shown three times and never used being named, and by a recordless project showing nothing at all.

**Architecture:** One read: the most recent run records (bounded window), tallied against the entries that exist, using the same distinctive-words-in-the-output judgment `_strengthen` already trusts — extracted to one shared function so the two can never disagree about what "used" means. No state, no counters stored, no action taken on the numbers.

**Tech Stack:** Python 3.10, pytest + pytest-asyncio. No new dependencies.

**Spec:** docs/superpowers/specs/2026-08-24-earning-its-keep-design.md

## Global Constraints

- **One judgment**: the used-decision is a single function shared by wear and the accounting.
- **Reporting, never acting**: nothing retires, moves, or reweighs anything based on these numbers.
- **Silence over zeros**: no records → no accounting lines; every prior report surface byte-identical.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **440 passed** at `2379d97` with docker running; **410 passed, 30 skipped** with it stopped. Both must stay green.
- Comment style: sparse. Commits end with the model trailer, per CLAUDE.md.

## Vocabulary guard

A run **used** what it was **shown**; an entry can be **unused**. Banned beyond earlier lists: *utility, metric, dashboard, score, telemetry, analytics*.

---

### Task 1: the accounting

**Files:**
- Modify: `src/poieo/memory.py` (the shared used-judgment; the accounting read), `src/poieo/learn.py` (`_strengthen` uses the shared judgment), `src/poieo/cli.py` (print)
- Test: `tests/test_cli_memory.py`

**Interfaces:**
- `_used_in(fact, record) -> bool` — the wear system's citation decision, extracted; `_strengthen` calls it.
- `memory_report` gains, only when run records exist: `runs_shown`, `runs_used`, and `unused` — entries that still exist, shown ≥ 3 times in the window (newest 50 records), used never.
- `poieo memory` prints `kept in mind  {used} of {shown} recent runs used what they were shown` and one `unused` line per named entry.

- [ ] **Step 1: Write the failing tests**

```python
def test_memory_counts_the_runs_that_used_what_they_were_shown(): ...
def test_an_entry_shown_often_but_never_used_is_named(): ...
def test_an_entry_used_even_once_is_not_named(): ...
def test_a_vanished_entry_is_not_named_however_often_shown(): ...
def test_a_project_without_records_shows_no_accounting(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 415 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: poieo memory says whether the memory earns its keep`

---

### Task 2: document it and show it working

**Files:**
- Modify: `README.md`
- Test: by hand, per Step 2

- [x] **Step 1: README** — one paragraph: the report answers whether runs actually use what they are shown, names dead weight, and acts on none of it; attention-grade measurement waits for a serving stack that can report it
- [x] **Step 2: End to end by hand** — done 2026-08-25: four seeded records produced `kept in mind  1 of 4 recent runs used what they were shown` and `unused       rate-limits (shown 4 times, used never)`; artifacts cleaned before commit
- [x] **Step 3: The whole suite, both ways** — docker running: 445 passed in 19.13s; docker stopped: 415 passed, 30 skipped in 8.01s
- [x] **Step 4: Commit** — `docs: a memory that answers for itself`

---

## Done means

- The kept-in-mind line and the unused line appear exactly when true, computed with wear's own judgment.
- Nothing anywhere acts on the numbers; no state is written; a recordless project is silent.
- The serving-attention half is deferred in writing, in the spec, with its replacement point named.
