# Keepsakes Implementation Plan (Plan K)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Point, don't remember — an entry the pass writes is sealed to the exact content it was written against, doubt compares content instead of clocks, the original is one pointer away, and keepsakes nobody references are let go — provable by a touched-but-identical file raising nothing, a changed one raising the no-longer-matches line, and a lost keepsake falling back to the mtime line rather than silence.

**Architecture:** `src/poieo/blob.py`: a flat content-addressed store under `.poieo/blobs/` (sha256 names, tmp+rename, idempotent put, size cap). The pass seals its own entries' file anchors at write time (`sealed: {"path": "sha"}` in frontmatter — harness-written, inside the existing door). `doubts()` prefers the content comparison for sealed anchors. After the attic move, a successful pass lets go keepsakes referenced by nothing in `facts/` or `attic/` and older than the grace. Bytes never enter `memory/` or any prompt.

**Tech Stack:** Python 3.10, stdlib hashlib, pytest + pytest-asyncio. No new dependencies.

**Spec:** docs/superpowers/specs/2026-08-24-keepsakes-design.md

## Global Constraints

- **A keepsake is a copy, never a meaning**: losing one costs precision and the openable original, not a word — the sealed doubt falls back to mtime, silently.
- **The entry always lands**: over-cap, directory, missing target, store failure — each seals less and says so; none blocks the write.
- **Bytes reach no prompt and no file under `memory/`.**
- **Collection is the one true deletion**, legal only for unreferenced runtime copies past the grace; failures skip and log.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **426 passed** at `1bff03b` with docker running; **396 passed, 30 skipped** with it stopped. Both must stay green.
- Comment style: sparse. Commits end with the model trailer, per CLAUDE.md.

## Vocabulary guard

An anchor is **sealed**; the copy is a **keepsake**; old unreferenced keepsakes are **let go**. Banned beyond earlier lists: *blob, hash, content-addressed, GC, snapshot, dedupe*.

---

### Task 1: the store

**Files:**
- Create: `src/poieo/blob.py`
- Test: `tests/test_blob.py`

**Interfaces:**
- `keep(project_dir, path) -> str | None` — copy the file into `.poieo/blobs/<sha256>` via tmp+rename; same content twice is a no-op returning the same name; over the cap (8 MB, one constant) or unreadable → None, logged.
- `kept(project_dir, sha) -> Path | None` — the keepsake's path, or None.
- `digest(path) -> str | None` — the sha of a file as it is now (streamed), None on any trouble.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_same_content_kept_twice_is_one_keepsake(): ...
def test_a_kept_file_reads_back_byte_identical(): ...
def test_an_over_cap_file_is_declined(): ...
def test_keep_never_raises(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 400 passed, 30 skipped (docker stopped)
- [x] **Step 5: Commit** — `feat: a place to keep the exact bytes an entry was written against`

---

### Task 2: the pass seals its entries

**Files:**
- Modify: `src/poieo/learn.py` (seal at `_write_entry` time), `src/poieo/memory.py` (`sealed` frontmatter field; load-check that sealed names a real anchor)
- Test: `tests/test_learn.py`, `tests/test_memory.py`

**Interfaces:**
- Writing an entry with anchors: each anchor whose path part is an existing file at/under the cap is kept and named in `sealed:`; directories and over-cap files are skipped (a note in the pass record for the over-cap case); the entry lands regardless.
- `_Frontmatter` gains `sealed: dict[str, str]`; `check_memory` rejects a `sealed` key naming an anchor the entry does not have.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_file_anchor_is_sealed_when_the_pass_writes(): ...
async def test_a_directory_anchor_is_not_sealed_and_the_entry_lands(): ...
async def test_an_over_cap_anchor_is_skipped_and_noted(): ...
def test_sealed_naming_a_missing_anchor_fails_at_load(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite**
- [ ] **Step 5: Commit** — `feat: the pass seals its entries to what they were written against`

---

### Task 3: doubt compares content

**Files:**
- Modify: `src/poieo/memory.py` (`doubts` prefers the seal)
- Test: `tests/test_cli_memory.py`

**Interfaces:**
- A sealed anchor: gone stays gone; content matching the seal raises nothing (even when freshly touched); content differing raises "no longer matches what it was written against"; a missing keepsake falls back to the mtime line silently.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_touched_but_identical_sealed_anchor_raises_nothing(): ...
def test_changed_content_raises_the_no_longer_matches_line(): ...
def test_a_lost_keepsake_falls_back_to_the_mtime_line(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite**
- [ ] **Step 5: Commit** — `feat: sealed anchors doubt by content, not clocks`

---

### Task 4: letting go, and the docs

**Files:**
- Modify: `src/poieo/learn.py` (collection after the attic move), `README.md`
- Test: `tests/test_learn.py`; by hand, per Step 3

**Interfaces:**
- After the attic move on a successful pass: keepsakes named by no `sealed:` across `facts/` and `attic/`, older than the grace, are deleted and listed in the pass record (`let_go`). Failures skip and log.

- [ ] **Step 1: Write the failing tests**

```python
async def test_an_old_unreferenced_keepsake_is_let_go_and_listed(): ...
async def test_a_keepsake_referenced_from_the_attic_survives(): ...
async def test_a_fresh_keepsake_survives(): ...
```

- [ ] **Step 2: README** — one paragraph: entries the project learns are sealed to the content they were written about; doubt means the content really differs; the kept original is under `.poieo/blobs/`; unreferenced keepsakes are let go
- [ ] **Step 3: End to end by hand** — in the worked example: a mock pass writes a sealed entry; touch the anchored file (identical) and see no doubt; change it and see the no-longer-matches line; open the keepsake and see the original bytes; clean before commit
- [ ] **Step 4: The whole suite, both ways** — paste both summary lines
- [ ] **Step 5: Commit** — `feat: keepsakes nobody references are let go` / `docs:` as fits the final diff

---

## Done means

- A pass-written entry with a file anchor carries `sealed:`; the keepsake reads back byte-identical; same content twice is one copy.
- Doubt for sealed anchors is precise: touched-identical silent, changed loud, lost-keepsake falls back — never silence about a real change.
- Collection removes only unreferenced, old, runtime copies, and says so; references from the attic protect.
- No bytes under `memory/`, no bytes in any prompt, and every prior surface byte-identical when nothing is sealed.
