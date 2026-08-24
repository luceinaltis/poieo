# Keepsakes Design

**Date:** 2026-08-24
**Status:** Approved for planning
**Roadmap:** a long memory — the files slice
**Builds on:** docs/superpowers/specs/2026-08-24-learning-pass-design.md, docs/superpowers/specs/2026-08-24-memory-upkeep-design.md

## Goal

An entry that names a file is anchored to a *path*, and paths are the least
durable thing about a file: contents churn under the same name, and the
upkeep slice can only say "it changed after you wrote this" from an mtime —
true of every touch, meaningful about none. The source design's rule for
files is **point, don't remember**: keep the text distillation in the
memory, keep the bytes it was written against where they can be opened when
detail matters, and never paste the bytes into a prompt.

This slice implements that rule for what poieo actually has today: files of
any kind in a task's folder. An entry the pass writes gets its anchors
**sealed** — the exact content it was written against is kept, content-
addressed, under `.poieo/` — so doubt becomes precise ("the content
differs", not "something touched the file"), the original is one pointer
away when a person wants it, and keepsakes nobody references anymore are
let go.

## The one idea

**A keepsake is a copy, not a meaning.** The entry's words stay the memory;
the kept bytes are runtime material, stored by content hash in
`.poieo/blobs/` (idempotent: same content, same name, one copy), never
injected into any prompt, and safe to lose — losing a keepsake costs the
precise comparison and the openable original, never a word of what was
learned. That places blobs exactly where episodes and strength live: below
git, beside the other things a machine keeps for itself.

Sealing happens where writing already happens: **the learning pass**, whose
validated door gains no new verb — when it writes an entry with anchors, it
also snapshots each anchored file as it is that night and stamps the
frontmatter:

```
---
anchors: ['notebook/feeds.md']
sealed: {"notebook/feeds.md": "2f6a…"}
source: ["20260824T…"]
---
```

A person may seal by hand the same way (compute a hash, write the line) or
not bother; unsealed anchors keep the mtime heuristic they have today.

## Decisions already made (with the user)

- **Description before pixels, and pixels never in prompts.** The source
  design's image rule holds in general form: what reaches a prompt is
  always the entry's text; the kept original is opened by a person (or a
  later tool) on demand. Auto-injecting file contents stays an anti-goal.
- **The vision half waits for its consumer.** Captioning a file with a
  vision model (`describer` role) is deferred until poieo has a vision-
  capable role and workloads that produce images — building it now would
  be exactly the unconsumed machinery the design's governing rule bans.
  When it arrives, it slots into the same seal step.
- **Bounded, always.** A file over the size cap (8 MB) is not kept — the
  entry still lands, unsealed, and the pass record says why. Blob hoarding
  is an anti-goal; so is a night's work failing over a fat file.
- **Keepsakes are collectable.** Runtime copies referenced by no entry —
  neither in `facts/` nor the attic — are removed by the pass after a
  grace, the one true deletion in the system, legal precisely because a
  keepsake is a copy: the meaning it backed is either alive (and keeps its
  reference) or was itself set aside and attic'd with its reference intact.

## The store

`.poieo/blobs/<sha256>` — flat, content-addressed, written via tmp+rename
so a torn write cannot leave a wrong body under a right name. Putting the
same content twice is a no-op. Nothing under `memory/` ever holds bytes;
`sealed:` holds names.

## What seals, when

On a successful pass, for each entry the pass writes: every anchor whose
path part names an existing **file** (directories are not sealed — a
directory's "content" is not a thing to keep) at or under the size cap is
copied into the store and named in `sealed:`. Failures seal less and say
so; the entry always lands.

## What the seal buys

The upkeep doubt for a sealed anchor compares content, not clocks:

```
second look  feeds-note names notebook/feeds.md, which no longer matches what it was written against
```

- Touched-but-identical files raise nothing (the mtime heuristic's false
  positive, gone).
- The kept original is at `.poieo/blobs/<sha>`, one `poieo memory` line
  away from being opened by hand — the lazy fetch, reduced to what it is.
- A gone file still reads as gone; an unsealed anchor keeps today's mtime
  line.

## Letting go

After the attic move, a successful pass collects: every sha named by no
`sealed:` in `facts/` or `attic/`, whose blob file is older than the grace
(the attic's 90 days, same constant family), is deleted, and the pass
record lists what was let go. A collection failure is logged and skipped —
the rule that nothing here is worth failing a pass over reaches its last
clause.

## Out of scope (deferred, with their guardrails kept)

- **Vision distillation** (`describer` role, captions of images) — with
  its consumer; the seal step is where it will live.
- **Excerpts of over-cap files, reproduction pointers** — until a real
  workload hits the cap and shows what an excerpt should be.
- **Sealing human-written entries automatically** — sealing is the pass's
  act on its own entries; a person's entry is sealed when the person says
  so, by writing the line.
- **Blobs for episode outputs, run artifacts** — episodes already keep
  their own text unclipped; bytes join them when something consumes bytes.

## Vocabulary

An anchor is **sealed**; the kept copy is a **keepsake**; old unreferenced
keepsakes are **let go**. Banned beyond the earlier lists: *blob, hash,
content-addressed, GC, snapshot, dedupe* (the frontmatter key `sealed` and
the folder name `blobs` are format, not interface, exactly as `scope` and
`.poieo` already are).

## Failure handling

| | |
|---|---|
| **anchor target is a directory** | not sealed, no complaint — anchors to places keep the mtime line. |
| **anchor target missing at seal time** | not sealed; the gone-line will say so at the next report. |
| **file over the cap** | not sealed; one pass-record note; the entry lands. |
| **store write fails** | that anchor stays unsealed; logged; the entry lands. |
| **keepsake missing at doubt time** | the sealed comparison silently falls back to the mtime line — a lost copy costs precision, never silence. |
| **`sealed:` naming an anchor the entry does not have** | fails at load naming the file, like every typed claim. |
| **collection failure** | logged, skipped, the pass stands. |

## Testing

- Same content kept twice is one keepsake; a torn write cannot corrupt one.
- A pass-written entry with a file anchor is sealed; directory anchors and
  over-cap files are not, and the entry lands anyway.
- A sealed anchor: touched-but-identical raises nothing; changed content
  raises the no-longer-matches line; a lost keepsake falls back to mtime.
- Collection: an unreferenced old keepsake is let go and listed; one
  referenced from the attic survives; a fresh one survives.
- Nothing under `memory/` ever contains bytes; no prompt ever contains a
  keepsake.

## Implementation split

One plan (K), four tasks: the store; the pass seals; doubt compares
content; collection, documentation, and the worked example.
