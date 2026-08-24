# Memory Connections Design

**Date:** 2026-08-24
**Status:** Approved for planning
**Roadmap:** a long memory — the graph slice
**Builds on:** docs/superpowers/specs/2026-08-24-project-memory-design.md

## Goal

A memory of loose facts answers only the question you thought to ask. The
entry that says *split batches over 50* is worth little without the one that
says *why the api started rejecting them* — and retrieval by shared words
will fetch one and strand the other, because relatedness is not similarity.

This slice lets entries name each other, and makes retrieval follow one such
connection outward from what it already chose. What a person judged related
arrives together, even when no word is shared.

## The one idea

**A connection is a judgment, and a judgment lives in markdown.** Who is
connected to whom is written in the entry files — prose mentions and a small
frontmatter field — where a person writes it, reviews it, and git diffs it.
Nothing here is scored, weighted, or learned; the machine's only contribution
is *following* what was declared. (Learned strength arrives with the
mechanism that learns it, in a later slice, and lives in the derived index
when it does. Similarity is never stored as a connection — the pairs an
embedding ranks highest include exact contradictions.)

The second half is a governing rule taken directly from the source design:
**a kind of connection exists only while a mechanism consumes it.** This
slice ships exactly the kinds it consumes and no others:

| kind | written as | consumed by |
|---|---|---|
| mention | `[[slug]]` in the body | retrieval expansion, either direction |
| leans on | `links: {depends_on: [slug]}` | expansion, forward; the report flags a lean on a set-aside entry |
| disagrees | `links: {contradicts: [slug]}` | the report lists the pair for a person to resolve |
| supersedes | `superseded_by:` (already exists) | retrieval exclusion (already exists) — not a new spelling |

`caused_by` is deliberately absent: its consumer is a debugging traversal
that does not exist yet. It arrives with that traversal or not at all —
an unconsumed kind is ontology rot.

## Decisions already made (with the user)

These come from the source design and hold from day one:

- **Similarity is never a connection.** Embedding scores are candidate
  screening at most (a later slice), never stored topology.
- **No weights in markdown, ever.** When learned strength arrives (P4), it
  lives in the derived index. The human-audited layer stays a diff of
  meaning.
- **A disagreement is resolved by a person or by evidence, never by one
  model's judgment deleting one side.** This slice only *surfaces* the pair;
  resolution stays manual until compaction ships, and even then it demotes
  rather than deletes.
- **One hop, behind the same interface.** Seeds in, ranking out — so that
  spreading activation can replace the hop later without moving a seam.

## What connects to what

A mention is prose: `see [[feeds-order]]` anywhere in the body. It reads as
writing, costs nothing to author, and is deliberately untyped — it means
*these belong near each other*, no more. A mention of an entry that does not
exist is legal and inert: it marks something worth writing, not an error.

The typed connections are frontmatter, because a type is a claim worth
validating:

```
---
scope: [importer]
links:
  depends_on: [batch-cap]
  contradicts: [old-retry-advice]
---
Retry a refused batch once, after the rate-limit window. [[rate-limits]]
```

- Only `depends_on` and `contradicts` are legal keys; anything else fails at
  load naming the file, like every other typo in a spec poieo reads.
- A frontmatter link must name an entry that exists — a dangling typed claim
  is a typo, and it fails at load naming the file. (This tightens
  `superseded_by` the same way, which shipped unvalidated in the first
  slice.) Prose mentions stay free; typed claims are checked.
- Leaning on a set-aside entry is legal — the report flags it, nothing
  breaks. Setting an entry aside never becomes an action that can fail.

## What retrieval follows

Expansion runs after the ranking the first slice established, on entries the
task could already see:

- Every directly-chosen entry keeps its place; neighbors join **after all
  direct hits**, in the order of the seed that brought them. Direct evidence
  before association, always.
- A **mention** is followed in either direction — nearness is symmetric.
- **Leans on** is followed forward only: what you chose needs what it leans
  on; what it leans on does not need it.
- **Disagrees** is never followed. Its consumer is the report; dragging a
  disputed entry into prompts by association is how confusion spreads.
- One hop means one hop. A neighbor's neighbors stay home; deeper travel is
  the later slice's spreading activation.
- Every filter still applies to a neighbor: out of scope stays out, set
  aside stays out, and the budget still cuts whole entries, best first.

The fallback contract is unchanged and cheap to keep: expansion happens
after candidate selection, on parsed entries both backends share, so the
scan and the index still return the same block.

## What the report says

`poieo memory <folder-or-card>` grows two sections, present only when true:

```
disagreements    batch-cap ↔ old-retry-advice
second look      retry-window leans on a set-aside entry (old-batch-cap)
```

Both are computed from the files at read time — no queue, no state, nothing
written. The disagreement list is the design's "resolution queue" reduced to
what it structurally is before compaction exists: a standing question shown
to the person who can answer it.

## Out of scope (deferred, with their guardrails kept)

- `caused_by`, and any traversal tool for the model (`expand`-style) — the
  kind arrives with its consumer.
- Spreading activation, learned edge strength, Hebbian reinforcement — the
  hop's interface (seeds in, ranking out) is the seam they replace.
- Machine-authored connections — link judgment at save time belongs to
  compaction (P3); until then every connection is a person's.
- Git-hook anchor revalidation and cascade re-checking — they ship with
  compaction, which is what can act on them; the report's "second look"
  line is this slice's honest fraction of that machinery.
- Similarity-screened link candidates (P4+), never similarity-as-topology.

## Vocabulary

In the interface an entry **mentions** another, **leans on** it, or
**disagrees with** it; a lean on a set-aside entry earns a **second look**.
Frontmatter keys keep the design's names (`links`, `depends_on`,
`contradicts`) exactly as `scope` and `anchors` already do — the file format
is spec territory, the output is not. Words that must not reach a prompt or
CLI output, added to the first slice's list: *graph, edge, node, hop,
traversal, expansion, ontology*.

## Failure handling

| | |
|---|---|
| **unknown link kind** | fails at load, naming the file |
| **typed link to a missing entry** | fails at load, naming the file and the missing name |
| **mention of a missing entry** | legal, inert — it marks something worth writing |
| **mention of a set-aside or out-of-scope entry** | followed and then filtered, so it arrives nowhere; no error |
| **a disagreement pair** | listed once in the report, injected never via connection |
| **lean on a set-aside entry** | legal; one report line |
| **malformed entry mid-residency** | as the first slice: skipped with a warning at run time, fatal at load |

## Testing

- A mentioned entry with no shared words arrives beside its seed — the point
  of the slice, written first.
- Direction: mentions both ways, leans-on forward only, disagrees never.
- Every first-slice filter holds for neighbors: scope, set-aside, budget,
  fallback equivalence, and one hop only.
- Load failures: unknown kind, dangling typed link, dangling
  `superseded_by`; and a dangling mention that must *not* fail.
- The report lists a disagreement once, flags a stale lean, stays silent
  when there is nothing to say, and still writes nothing.

## Implementation split

One plan (G), four tasks: reading the connections (parsing and load
validation); following them (one-hop expansion inside retrieval); saying
what they imply (`poieo memory` sections); documentation and the worked
example extended with an entry that only arrives by being mentioned.
