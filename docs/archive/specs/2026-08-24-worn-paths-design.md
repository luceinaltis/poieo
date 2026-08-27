# Worn Paths Design

**Date:** 2026-08-24
**Status:** Approved for planning
**Roadmap:** a long memory — the association slice
**Builds on:** docs/specs/2026-08-24-memory-connections-design.md, docs/specs/2026-08-24-learning-pass-design.md

## Goal

Connections today are all equally loud. The mention that mattered in twenty
runs and the mention that never mattered once arrive in the same order, and
when the budget cuts, it cuts blind. This slice makes **use wear the paths**:
a connection between entries that actually helped together, in work that
succeeded, carries later retrievals sooner and further — and a path nobody
walks fades back to ordinary.

## The one idea

**Strength is earned three ways at once, or not at all.** A connection
strengthens only when (a) both entries were not merely shown but *cited* —
their own words surface in what the run actually produced — (b) the run
**succeeded**, and (c) even then, time decays every strength and no entry's
connections can grow without bound: an entry connected to everything has
weak claims on each (the fan effect). Co-presence alone earns nothing —
reinforcing what retrieval already picks is how a memory talks itself into
a rut. All three factors come from the source design, kept whole.

The second half: **strength is emphasis, never meaning.** What connects to
what stays a judgment in markdown; how *worn* a connection is lives in a
runtime file (`.poieo/strength.json`), gitignored, never shown as a
connection, never written into an entry. Delete it and the project forgets
which paths were worn — and relearns them by working — while every meaning,
every connection, every entry stands untouched. This keeps the derived
index exactly as promised (deletable, losing nothing) by keeping strength
out of it entirely.

## Decisions already made (with the user)

From the source design, held here:

- **Reinforcement lives in the learning pass.** The design puts Hebbian
  strengthening in the sleep-time write path, and poieo keeps it there: the
  pass is already the serialized single writer with exactly-once batches
  (the bookmark), so strengthening inherits both for free and stays off the
  critical path. A pass that fails strengthens nothing; the reread covers it.
- **Citation is a proxy, and says so.** Until the serving stack can report
  what the model attended to (the instrumentation slice), "cited" means an
  entry's distinctive words appear in the run's own output — crude, local,
  and honest about being a stand-in.
- **Only declared connections strengthen.** The design eventually grows
  co-use edges of the machine's own; here, strength accrues only to pairs a
  person (or a pass) already connected in markdown. A learned association
  with no declared connection is the instrumentation slice's business,
  when the signal is real.
- **Strength modulates, never overrules.** The direction rules stand:
  mentions both ways, leans-on forward, disagrees never — no amount of wear
  makes retrieval follow what it would not follow. And direct evidence
  still beats association: no neighbor outranks a direct hit.
- **Same interface, further reach.** Retrieval is still seeds in, ranking
  out. With no strength anywhere, it behaves exactly as the connections
  slice shipped — one hop, seed order. Where paths are worn, neighbors
  arrive in worn order, and a strong path carries activation one hop
  further; an unworn second hop is never taken. (The design's
  restart-probability tuning per kind of work waits for poieo to have kinds
  of work; a fixed damping stands in, named in one place.)

## What is recorded, where

**The run records what it was shown.** An episode gains `shown`: the entry
slugs the run's memory block carried, recomputed at record time by the same
selection that built the block. This is what lets the pass judge citation
against the run's own unclipped output, and it makes the episode honest:
the full record now includes what the project had in mind.

**Strength lives beside the other runtime records:**

```
<tasks folder>/.poieo/strength.json
```

One small JSON object: undirected pair → weight and when it was last
earned. Decay is applied by age whenever a weight is read (a half-life, one
constant), so an untouched file simply fades — no sweeper, no schedule.
After every reinforcement, an entry whose total connected weight exceeds
the cap has all its weights scaled down proportionally: the fan effect,
enforced at write time.

## How the pass strengthens

After a successful pass (the same success that moves the bookmark), for
each **completed** run in the batch:

1. The run's cited entries: those among its `shown` whose distinctive words
   (the retrieval tokenizer, glue removed) overlap the run's summary and
   outputs by at least two words.
2. Every pair of cited entries that is **declared connected** in markdown
   earns one reinforcement.
3. Decay and the fan cap apply as the weights land.

A failed run strengthens nothing (factor b). A run that cited one entry or
none strengthens nothing (there is no pair). A failed pass strengthens
nothing (exactly-once rides the bookmark).

## How retrieval spends it

The neighbor pass becomes a spread with the same guarantees:

- Direct hits first, always, in score order — unchanged.
- Each chosen entry pushes activation across its declared, direction-legal
  connections. A declared connection carries at full base value — so with
  no strength anywhere the first hop is exactly the connections slice, seed
  order, slug tie-break. Wear adds to a connection's carry, so worn
  neighbors of the same seed arrive first, and a neighbor two chosen
  entries share counts twice.
- A second hop is taken **only across worn connections**: the carry beyond
  the first hop is the strength alone, so zero strength means one hop
  means one hop, exactly as today.
- Every filter still holds for everything reached: scope, set-aside, the
  whole-entry budget, and byte-identical results from the file scan and
  the index.

## Out of scope (deferred, with their guardrails kept)

- **Attention-measured utility** and machine-created co-use associations —
  the instrumentation slice; until then citation stays a declared proxy.
- **Restart tuning per kind of work** — waits for kinds of work to exist.
- **Strength-informed promotion or demotion of entries themselves** (an
  unworn entry is *not* set aside by fading — set-aside remains a judgment,
  a person's or a pass's, never a counter's).
- **Weights in markdown, ever.** Also unchanged: no similarity anywhere,
  no deletion anywhere.

## Vocabulary

Almost nothing here reaches the interface, and that is the point: wear is
felt as better ordering, not seen as a number. If it must be spoken of, a
connection is **worn** or **well-worn**; entries **helped together**. Words
that must not reach a prompt or CLI output, beyond the earlier lists:
*strength, weight, activation, spread, decay, reinforcement, Hebbian,
citation, half-life, damping*.

## Failure handling

| | |
|---|---|
| **no strength file** | everything behaves as the connections slice; the file appears on first reinforcement. |
| **corrupt strength file** | logged, treated as empty, rewritten on next reinforcement. Emphasis lost, meaning intact. |
| **deleted strength file** | same, silently — it is runtime memory of what worked, relearnable by working. |
| **an entry in the file no longer exists** | its pairs are ignored on read and dropped on next write. |
| **a run with no `shown`** (pre-slice episodes) | strengthens nothing, distills as before. |
| **strength write fails** | logged; the pass's distillation stands. Emphasis is never worth failing a pass over. |

## Testing

- The three factors, each alone insufficient: shown-but-uncited pairs earn
  nothing; cited pairs in a failed run earn nothing; unconnected cited
  pairs earn nothing; connected, cited, succeeded earns exactly once per
  pass — and a failed pass earns nothing, then exactly once on the reread.
- Runaway is impossible by construction: reinforce one pair many times and
  the fan cap holds its entry totals; an untouched weight decays.
- Ordering: the worn neighbor of a seed beats its unworn sibling; a worn
  two-hop path arrives and an unworn one never does; no neighbor ever
  outranks a direct hit; with an empty strength file every connections-
  slice test still passes unchanged.
- The scan and the index still agree byte for byte.
- Episodes carry `shown`; a memoryless project's episodes carry nothing new.

## Implementation split

One plan (I), five tasks: episodes record what was shown; the strength
store (decay, fan cap, atomic writes); the pass strengthens; retrieval
spends the wear; documentation and the worked example with a worn path the
user can feel.
