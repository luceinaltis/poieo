# Memory Connections Implementation Plan (Plan G)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An entry a person judged related arrives beside the entry that names it, even when the two share no word — provable by one test where a mentioned entry with zero token overlap joins the block, and by the fallback still returning byte-identical results.

**Architecture:** Connections live in the entry files: `[[slug]]` mentions in prose, `links: {depends_on: [...], contradicts: [...]}` in frontmatter. Nothing new is stored anywhere — expansion is plain code over the parsed entries both lookup backends already share, and the report's two new sections are computed from the files at read time. `supersedes` keeps its existing spelling (`superseded_by:`); `caused_by` does not ship (no consumer yet).

**Tech Stack:** Python 3.10, pytest + pytest-asyncio (asyncio_mode=auto). No new dependencies, no new index tables.

**Spec:** docs/superpowers/specs/2026-08-24-memory-connections-design.md

## Global Constraints

- **Direct evidence before association.** Every directly-chosen entry outranks every neighbor; neighbors join in the order of the seed that brought them.
- **Every first-slice filter holds for neighbors:** scope, set-aside exclusion, whole-entry budget, one hop only, fallback equivalence.
- **Disagrees is never followed.** Its only consumer is the report.
- **Typed claims validate at load; prose mentions never fail.** A dangling `depends_on`/`contradicts`/`superseded_by` names the file and the missing name. A dangling `[[mention]]` is legal and inert.
- **Nothing is written anywhere** by any of this: no queue file, no state, no new index table. `poieo memory` stays read-only.
- **No weights, no similarity, anywhere.** The human-audited layer stays a diff of meaning.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **316 passed, 30 skipped** at `da18be1` with docker stopped; **346 passed** with it running. Both must stay green.
- Comment style: sparse, explain constraints, not mechanics. Commits end with the model trailer, per CLAUDE.md.

## Vocabulary guard

An entry **mentions** another, **leans on** it, or **disagrees with** it; a lean on a set-aside entry earns a **second look**. Frontmatter keys keep the design's names (`links`, `depends_on`, `contradicts`), exactly as `scope` and `anchors` already do. Words that must not reach a prompt or CLI output, beyond the first slice's list: *graph, edge, node, hop, traversal, expansion, ontology*.

---

### Task 1: an entry can name another

**Files:**
- Modify: `src/poieo/memory.py` (`_Frontmatter` gains `links`; `Fact` gains parsed mentions; cross-file validation in `check_memory`)
- Test: `tests/test_memory.py`

**Interfaces:**
- `links` frontmatter: a mapping whose only legal keys are `depends_on` and `contradicts`, each a list of entry slugs. Anything else fails at load naming the file.
- Body `[[slug]]` mentions are parsed onto the entry. Dangling ones are legal.
- Cross-file check (typed links and `superseded_by` must name entries that exist) lives with `check_memory`, because a single file cannot see its siblings. The lenient run-time loader stays lenient.

**Why this is first.** Everything else consumes what this parses, and the validation half is independently worth landing: a typo in a typed claim currently fails silently forever.

- [x] **Step 1: Write the failing tests**

```python
def test_a_mention_in_the_body_is_read(): ...
def test_typed_links_in_frontmatter_are_read(): ...
def test_an_unknown_link_kind_fails_at_load_naming_the_file(): ...
def test_a_typed_link_to_nothing_fails_at_load_naming_both(): ...
def test_a_dangling_superseded_by_now_fails_at_load(): ...
def test_a_body_mention_of_nothing_is_legal(): ...
def test_leaning_on_a_set_aside_entry_is_legal_at_load(): ...
```

- [x] **Step 2: Run the tests to verify they fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 353 passed (docker running)
- [x] **Step 5: Commit** — `feat: a memory entry can name the entries it leans on`

---

### Task 2: retrieval follows one connection outward

**Files:**
- Modify: `src/poieo/memory.py` (`_recall` grows the neighbor pass)
- Test: `tests/test_memory_search.py`

**Interfaces:**
- After ranking and before the budget cut: for each chosen entry in rank order, collect connected entries — mentions either direction, leans-on forward only, disagrees never — that pass every existing filter and are not already chosen. Append after all direct hits, ordered by their seed's rank then slug. One hop; neighbors do not expand.
- The budget then cuts the combined sequence exactly as today.

**Why after ranking, not inside it.** A neighbor has no score of its own to argue with — its claim to the prompt is its seed's. Interleaving would let association outrank evidence.

- [x] **Step 1: Write the failing tests**

```python
def test_a_mentioned_entry_joins_despite_sharing_no_word(): ...   # THE test
def test_a_mention_is_followed_in_both_directions(): ...
def test_a_leaned_on_entry_joins_forward_only(): ...
def test_a_disagreeing_entry_is_never_dragged_in(): ...
def test_neighbors_come_after_every_direct_hit(): ...
def test_a_neighbor_out_of_scope_stays_out(): ...
def test_a_set_aside_neighbor_stays_out(): ...
def test_one_hop_means_one_hop(): ...
def test_the_budget_still_cuts_whole_entries_across_neighbors(): ...
def test_the_fallback_still_returns_the_same_entries(): ...
```

- [x] **Step 2: Run the tests to verify they fail** *(first pass caught the direction test scoring off the mention text itself — seed renamed so only reverse-following can pass it)*
- [x] **Step 3: Implement**
- [x] **Step 4: Run the full suite** — 363 passed (docker running)
- [x] **Step 5: Commit** — `feat: what an entry mentions arrives beside it`

---

### Task 3: the report says what the connections imply

**Files:**
- Modify: `src/poieo/memory.py` (`memory_report` gains the two computed sections), `src/poieo/cli.py` (print them)
- Test: `tests/test_cli_memory.py`

**Interfaces:**
- `disagreements`: each `contradicts` pair between two kept entries, listed once however many sides declared it.
- `second look`: each kept entry leaning on a set-aside one.
- Both sections appear only when non-empty. Nothing is written; the command stays read-only.

- [ ] **Step 1: Write the failing tests**

```python
def test_memory_lists_a_disagreement_once(): ...
def test_memory_flags_a_lean_on_a_set_aside_entry(): ...
def test_a_memory_with_nothing_to_say_adds_no_sections(): ...
def test_memory_is_still_read_only(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite**
- [ ] **Step 5: Commit** — `feat: poieo memory surfaces disagreements and stale leans`

---

### Task 4: document it and show it working

**Files:**
- Modify: `README.md` (extend the memory section: mentions, leans, disagreements)
- Modify: `examples/remembering/` — an entry that only arrives by being mentioned (`feeds-order`, no shared word with the importer card, mentioned by `batch-cap`)

- [ ] **Step 1: The example** — `feeds-order.md` + the mention in `batch-cap.md`; confirm the exporter still sees neither (scope holds through connections)
- [ ] **Step 2: README** — one paragraph in the memory section; interface words only
- [ ] **Step 3: The whole suite, both ways** — docker running and stopped; paste both summary lines
- [ ] **Step 4: End to end by hand** — `poieo memory` on the importer card shows `feeds-order` arriving with no shared word; a temporary `contradicts` pair appears once under disagreements and vanishes when one side is set aside — at which point anything leaning on it earns the second-look line; delete the derived index mid-way and nothing changes
- [ ] **Step 5: Commit** — `docs: a memory whose entries know each other`

---

## Done means

- An entry with no word in common with the task arrives because a chosen entry mentions it — and the scan and the index agree byte for byte.
- No neighbor ever outranks a direct hit, escapes scope, resurrects a set-aside entry, or brings its own neighbors.
- A typo in a typed claim fails at load naming the file; a prose mention never fails anything.
- `poieo memory` answers "what disagrees, and what needs a second look" from the files alone, and still writes nothing.
- `git diff` of `memory/` shows judgments, never scores: no weights, no similarity, no new file kinds.
