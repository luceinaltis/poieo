# Earning Its Keep Design

**Date:** 2026-08-24
**Status:** Approved for planning
**Roadmap:** a long memory — the measurement slice
**Builds on:** docs/specs/2026-08-24-worn-paths-design.md

## Goal

The source design's last principle is measurement built in: this field's
benchmarks are immature, so a memory must prove itself on its own
workload, with its own numbers. poieo already records everything the
question needs — every run's record says what it was shown and what it
produced — and nothing yet adds it up. This slice makes `poieo memory`
answer the design's closing question directly: **is the memory earning its
keep?**

## The one idea

**The accounting is a read, not a system.** Over the recent run records:
how many runs were shown entries, how many actually used what they were
shown (the same words-in-the-output judgment the wear system already
trusts), and which entries are shown again and again without ever being
used — the dead weight a person should look at. No counters are stored, no
state accrues; delete nothing, configure nothing, the records already hold
the answer.

```
kept in mind  9 of 14 recent runs used what they were shown
unused        zebra-note (shown 6 times, used never)
```

## Decisions already made (with the user)

- **The serving half stays deferred, and the spec says why.** Measuring
  which injected words the model truly attended to requires exporting
  attention mass from the serving engine — a change to vLLM-class
  infrastructure, not to poieo. The source design anticipated exactly
  this: the first implementation must run on behavioral signals, and it
  does — the used-judgment here is the wear system's, shared, so the two
  numbers can never disagree about what "used" means. When a serving
  stack can report attention, it replaces this judgment in one place.
- **Ablation stays deferred with it.** Rerunning work minus one entry to
  measure causal lift spends real model calls; it arrives when someone has
  a workload worth spending them on, as a command a person runs, never a
  background habit.
- **Naming dead weight is reporting, not acting.** An entry shown often
  and used never is *named*, nothing more — retiring it stays a judgment,
  a person's or the pass's, never a counter's. (The same rule wear
  follows: no counter ever sets an entry aside.)

## What is counted

Over the most recent run records (a bounded window, newest first): each
completed run that was shown entries counts once; it counts as *used* when
at least one shown entry's distinctive words surface in the run's summary
or outputs. Per entry: times shown, times used; an entry shown at least
three times and used never earns the `unused` line. Failed runs and
records from before `shown` existed count nothing.

## Out of scope (deferred, with their guardrails kept)

- Attention-measured usefulness and machine co-use associations — with a
  serving stack that can report them.
- Ablation reruns — as an explicit command, when a workload warrants the
  spend.
- Any automatic action on the numbers — the accounting informs the person
  and the pass informs itself; neither retires an entry by count.

## Vocabulary

A run **used** what it was **shown**; an entry can be **unused**. Banned
beyond the earlier lists: *utility, metric, dashboard, score (in output),
telemetry, analytics*.

## Failure handling

| | |
|---|---|
| **no run records** | no accounting lines at all — not zeros, silence. |
| **records without `shown`** | count nothing; the window still reads the newest records first. |
| **an unreadable record** | skipped, as everywhere. |
| **entries in records that no longer exist** | shown-counts still tally (the run was shown them); the unused line names only entries that still exist to be looked at. |

## Testing

- Runs that used what they were shown are counted as such, with the same
  judgment wear uses — pinned by sharing the function, not by a twin.
- An entry shown three times and never used is named; one used once is
  not; one that no longer exists is not named however often it was shown.
- A project with no records shows no accounting; prior report surfaces
  are byte-identical.

## Implementation split

One plan (L), two tasks: the accounting in the report; documentation and
the worked example.
