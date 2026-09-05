# Memory

`src/poieo/memory/`, `src/poieo/learn.py`, `src/poieo/strength.py`,
`src/poieo/blob.py`

Each task has a short-term journal, described in [tasks.md](tasks.md). Long-term
memory is project-wide and opt-in: the existence of
`memory/longterm.sqlite3` is the whole switch. A run receives one standing page
and a bounded selection of learned entries.

## Source data and derived data

The SQLite database is the sole source of truth for long-term memory. It holds:

- `page` — one project-wide text shown to every run;
- `entries` — durable statements and their typed metadata;
- `pieces` — the text units retrieval matches;
- `links` — mentions, dependencies, and contradictions used for association;
- `history` — every page or entry write, its writer, and before/after data;
- `meta` — the schema version.

An entry currently has one piece. The schema keeps those concepts separate so
retrieval can change its matching unit without changing entry identity. The
database's full-text tables are derived and may be dropped and rebuilt; one
indexes the shaped words used by autonomous recall and another indexes the raw
Unicode text used by a person's search. Everything under `memory/cache/` is
also derived: connection strength, anchored-file blobs, learning progress,
compiled build artifacts, and `embeddings.sqlite3` may be recreated or lost
without changing what the project knows.

The database is not a cache. Schema changes migrate rows forward in order.
Opening a database written by a newer schema is refused rather than guessed at;
deleting and rebuilding the file would delete the only copy.

## Page and entries

The page is written only by a person and shown whole, before learned entries.
Markdown comments are removed before it reaches a prompt. Its size has an
advisory budget because an oversized standing rule should be visible, but must
not become a way to stop every task.

An entry has a lowercase dash-separated slug, body, update time, and typed
metadata:

```yaml
scope: [global]                 # global, task ids, or project path prefixes
anchors: [src/poieo/card.py]   # path or path::symbol, never line numbers
source: [<run-id>]             # records that taught it; empty means a person
valid_from: 2026-08-24
superseded_by: replacement
links:
  depends_on: [another-entry]
  contradicts: [disputed-entry]
sealed:
  src/poieo/card.py: <content-digest>
```

`write_entry`, `write_page`, and `set_aside` are the write doors. They validate
the shape and append history in the same transaction. Setting an entry aside
marks `superseded_by`; it does not delete or rewrite the body. Startup validation
requires typed targets to exist and sealed paths to be anchors. Free-form
`[[mentions]]` may name an entry that has not been written yet.

## Recall

`read_memory(project, task)` rereads memory for every run and produces:

```text
What this project always requires:
<page>

What earlier work here has learned:
<selected entry bodies>
```

Recall first admits entries whose scope covers the task and excludes entries
that are set aside. It narrows and ranks them by shared distinctive words, each
worth more the fewer pieces hold it, with the same conservative plural
normalization on the task and the stored pieces. Word counts come from the
derived lookup when it exists and from reading every piece when it does not.
An anchor covering the task's folder receives priority. Direct mentions and
`depends_on` links can bring neighboring entries with a chosen one; learned
connection strength affects ordering but never changes the authored meaning.
A `contradicts` link is a veto against showing both sides together.

Matching controls order, not admission. In-scope entries with no match fill
remaining room after supported entries. Selection stops on whole-entry
boundaries within a fixed prompt budget; an oversized entry is skipped rather
than crowding out every entry below it.

A memory read that fails during a run logs a warning and returns less context.
Forgetting optional context is preferable to losing the primary work. Load-time
schema and cross-entry errors remain configuration failures.

## Browsing and search

The board reads a bounded graph of entries and the relationships they actually
declare: mentions, dependencies, contradictions, supersession, and learned
strength on those existing connections. Search similarity may highlight an
entry but never creates a relationship. Selecting an entry fetches its full
body, metadata, second-look reasons, and write history. The initial graph may be
truncated; search still considers every entry, with set-aside entries included
or excluded as the user chooses.

**Words** searches slugs and raw entry text through Unicode full-text lookup
with a substring fallback. This reader-facing index is separate from the
conservative word shaping used for autonomous recall, so adding a language or
changing search ranking cannot silently change what reaches a run.

**Meaning** requires an explicit `memory_embedder` role backed by Ollama or an
OpenAI-compatible embedding endpoint. It compares query and entry vectors by
cosine similarity. Vectors are cached by model, endpoint fingerprint, entry
slug, and body digest; a changed model or body is embedded again, and a damaged
cache is discarded and rebuilt. A first search therefore sends entry bodies to
the configured endpoint and should use the same privacy judgment as a task
prompt.

**Ask** requires an explicit `memory_searcher` role. It combines word and
meaning ranks, weighting word evidence more heavily, and gives only the bounded
shortlist to a tool-free completion. Unsupported citations are removed from
the answer. When meaning search is absent or fails, the response says that it
used words only. Queries and answers are not persisted; only derived search
indexes and caches may be updated.

## Run records and learning

The harness writes one full record under `runs/results/<run-id>.json` for every
card run. It includes status, outputs, summary, usage, and which entries were
shown. A pending question is the one legitimate
late revision: its record is replaced after the fixed answer completes the run.
Models have no tool for writing these records.

A learning pass reads successful-bookmark progress from the derived learning
log and processes a bounded oldest-first batch of unread run records. It makes
one model request through the binding's `learner` role. The model proposes; the
harness validates and writes:

- source ids are restricted to records actually shown;
- new slugs cannot escape the namespace or collide with an existing entry;
- typed links are resolved to a valid fixed point;
- the pass may add an entry or set one aside, but never overwrite or delete an
  existing body;
- the pass may suggest a page sentence, but only a person can write the page.

The bookmark advances only after a successful pass. A failed pass records its
failure and rereads the same records next time. An empty proposal is valid.
Daemon-scheduled learning waits until no armed task is busy and cannot stop the
daemon on failure.

## Upkeep and recovery

`poieo memory` derives its report at read time. It shows standing and set-aside
entries, unresolved contradictions, entries needing a second look because an
anchor or dependency changed, and recent evidence that recalled entries were
or were not used. Nothing automatically acts on this report.

Anchored-file blobs are content-addressed snapshots used to distinguish a real
content change from a touched timestamp and to keep the earlier bytes
inspectable. Keeping a blob is best-effort and size-bounded; failure does not
block the entry. Connection strengths decay and are capped; a corrupt or missing
strength file reads as empty.

To extend memory, preserve the single database as source of truth, record every
write in history, migrate forward without data loss, and keep retrieval indexes
rebuildable. New automatic writers require an explicit authority boundary at
least as strict as the learning pass. Reader-facing semantic search must remain
separate from autonomous recall unless that prompt-selection contract is
changed deliberately and tested as such.
