# Memory Upkeep Design

**Date:** 2026-08-24
**Status:** Approved for planning
**Roadmap:** a long memory — the lifecycle slice
**Builds on:** docs/superpowers/specs/2026-08-24-memory-connections-design.md, docs/superpowers/specs/2026-08-24-learning-pass-design.md

## Goal

A memory that only grows becomes a memory nobody trusts. Entries rot in
three ways today and nothing notices: the code an entry names gets deleted
or rewritten under it; an entry flagged for a second look sits flagged
forever because rechecking is nobody's job; and entries set aside pile up
in `facts/` until the folder reads like a graveyard. This slice gives the
memory its upkeep — **rot is noticed, the second look actually happens,
and the long-set-aside step out of the way — and still nothing is ever
deleted.**

## The one idea

**Upkeep needs no new machinery — only new eyes on old machinery.** The
report already computes standing questions from the files; it learns to see
two more kinds of rot. The learning pass already has exactly the verbs a
recheck needs — keep, or set aside with a replacement — so rechecking is
just *showing* the pass what is doubtful. And the attic is a `git mv`, not
a deletion: an entry past its grace moves to `memory/attic/`, out of every
load and every prompt, fully reversible by moving it back.

The source design wants revalidation driven by git hooks and commit
anchors. poieo's projects are not guaranteed to be git repositories, so rot
is judged from the filesystem alone: **an anchor whose target is gone, or
whose target changed after the entry was last written, is rot** — cruder
than a commit diff, but true wherever poieo runs, and wrong only in the
safe direction (a touched file that did not really change costs one
recheck, not one lost truth).

## Decisions already made (with the user)

- **The page stays behind a person, even for suggestions.** The pass may
  now *suggest* a page amendment — one line, recorded in the pass log and
  surfaced by `poieo memory` — but it lands in no file under `memory/`,
  and applying it is an edit only a person makes. The always-loaded layer
  keeps the highest gate there is.
- **Demote before delete, still — and the attic is not deletion.** An
  attic'd entry keeps its file, its frontmatter, its trail; `git log`
  knows where it went. Permanent deletion remains outside every slice.
- **No new state.** Rot and readiness-for-the-attic are computed from
  files and their mtimes at read time, exactly like disagreements and
  stale leans. Nothing writes a queue.

## What the report now sees

`second look` grows two reasons beside the stale lean, each computed at
read time and shown only when true:

```
second look  retry-note leans on old-cap, which is set aside
second look  batch-cap names notebook/feeds.md, which is gone
second look  feeds-order names notebook/, which changed after it was written
```

- **Gone:** an anchor path that no longer exists.
- **Moved under:** an anchor target modified more recently than the entry's
  own file — the code moved and the entry did not. (The entry's mtime is
  its "last written"; editing the entry is how a person clears the flag,
  which is exactly the right gesture: look, then touch.)

## How the second look happens

The learning pass's prompt gains one section: the entries currently under
a second look, with their reasons. The pass already knows what to do with
a doubtful entry — confirm it silently (do nothing), or retire it
(`set_aside` with what replaces it, possibly an entry proposed the same
pass). No new verbs, no new validation: the recheck rides the door that
already exists. A pass that fails changes nothing, as ever.

## The attic

On a successful pass, entries that have been set aside longer than the
grace (90 days, judged by the entry file's mtime — the set-aside edit is
the clock) move from `memory/facts/` to `memory/attic/`, **unless anything
still names them** in a typed way (`depends_on`, `contradicts`,
`superseded_by`) — moving a named entry would break the load-time
cross-check, so referenced entries wait, however old. Prose mentions do
not hold an entry back (a dangling mention is legal and always was).

The attic is outside every load: `load_facts` reads `facts/` alone, so
attic entries reach no prompt, no report, no index — and a person restores
one with `git mv` or a drag in a file manager. The move is the third and
last verb the pass will ever get, and it is the gentlest: it changes no
file's content at all.

## The page suggestion

The pass's answer may carry one more optional field:

```json
{"entries": [...], "set_aside": [...], "page": "Consider requiring ISO dates in the notebook."}
```

One line, recorded in `.poieo/learning.jsonl`, shown by `poieo memory` as
*the last pass suggests: …* until a newer pass suggests otherwise or
nothing. It never touches `memory/`, and there is deliberately no way to
"accept" it mechanically — the page is edited by hand or not at all.

## Out of scope (deferred, with their guardrails kept)

- **Commit-precise revalidation** (git hooks, anchor diffs) — when poieo
  projects are known to be repositories; mtime rot stands in, wrong only
  toward extra rechecks.
- **Automatic restore from the attic on re-reference** — restoring is a
  person's move; the pass does not reach into the attic at all.
- **Permanent deletion** — no slice gets it.
- **Symbol-level anchor checking** (`path::symbol` beyond the path part) —
  the path is checked; the symbol waits for tooling that can read one.

## Vocabulary

An entry is **gone** or **changed after it was written**; an old set-aside
entry **moves to the attic**; the pass **suggests** a page line. Banned
beyond the earlier lists: *rot, revalidation, stale (in output), grace
period, tombstone, archive, GC, lifecycle*. ("Second look" and "set aside"
continue to carry the weight.)

## Failure handling

| | |
|---|---|
| **anchor target unreadable rather than gone** | treated as present; upkeep never turns an I/O hiccup into doubt. |
| **an attic move fails midway** | logged; the entry stays where it is; the pass's other work stands. |
| **attic name collision** | the move is skipped and logged — the attic never overwrites either. |
| **a typed link into the attic (hand-made)** | fails at load naming both, exactly like any dangling typed claim. |
| **no second looks, nothing attic-ready, no suggestion** | the pass prompt, the report, and the pass log all look exactly as they did before this slice. |

## Testing

- Rot is seen: a gone anchor and a changed-after anchor each earn their
  second-look line; touching the entry clears the changed-after line.
- The recheck happens: the pass prompt carries the second-look section
  with reasons; a pass may set a doubted entry aside; a failed pass
  changes nothing.
- The attic: an old set-aside moves whole (content byte-identical); a
  typed-named one stays however old; a fresh one stays; attic entries
  reach no load, no report, no prompt; a collision is skipped.
- The suggestion: carried, recorded, shown, replaced by the next pass;
  never a file under `memory/`.
- With nothing doubtful and nothing old, every prior-slice surface is
  byte-identical.

## Implementation split

One plan (J), four tasks: the report sees rot; the pass rechecks (prompt
section + page suggestion); the attic move; documentation and the worked
example's e2e.
