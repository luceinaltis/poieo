# Task Notes Design

**Date:** 2026-08-23
**Status:** Approved for planning
**Roadmap:** tasks that work together

## Goal

A task can leave a note for another task, and that note is **never lost**.

Today a task remembers what it did and hears what the user told it, both
through its journal. This lets a task be the one telling — *the docs were
rebuilt, so the link checker should look again* — using the same file, the same
format, and the same words the user already uses.

## The one idea

**The journal is already a mailbox.** One markdown file per task, appended to
and never rewritten, re-read before every run, holding three kinds of line:
what the task did, what it failed at, and what the user said. This slice adds a
fourth kind — what another task said — and one tool for writing it.

Nothing else about the journal changes. It stays one file, still append-only,
still readable and writable by hand.

## The problem this has to solve first

A journal is a **record**; a note is a **message**, and they age differently.

A record may lose its oldest lines — recent history is what a task needs, and
only a bounded amount reaches the prompt. A message that falls off the end has
not aged out; it has been **lost**, and the sender got no signal.

Today that bound is a line count. Add notes to a counted stream and the failure
is silent: a busy task with a full journal never sees a note that was written
for it. That is a worse defect than the feature is a feature.

**This is already a latent bug.** `poieo note` writes into the same counted
stream, so a user's note can be buried today, before anyone reads it. Fixing
delivery fixes both.

## The fix: cut by position, not by count

A task writes a line to its own journal at the end of every run. **That line is
a bookmark.** Everything appended after it arrived while the task was not
looking.

So the journal is read as two parts:

```
New since you last worked:        everything after the bookmark — all of it,
                                  never trimmed by a line budget

What you did before that:         the tail of what came before — bounded, and
                                  allowed to age out
```

**The file is not split.** There is one journal, in time order, exactly as
now. The split happens when the journal is read for a prompt, and nothing is
written to mark it. A person opening the file sees the same boundary the task
does — their own last entry.

This is what makes loss structurally impossible: unread lines are selected by
*where they are*, not by *how many* there are, so no volume of notes can push
another note out before it has been seen once.

## Decisions already made (with the user)

- **Notes go in the journal.** Not a queue, not an inbox file, not a second
  format. Adding either would be a fourth word against DESIGN.md principle 7,
  and the journal already delivers.
- **A note does not wake anybody.** It is read at the recipient's next
  scheduled run. This is the whole loop-safety argument: two tasks that write
  to each other still run only on their own triggers, so there is no way to
  spin. It falls out of the design rather than being defended against.
- **A note is news, not a command.** The recipient is a model reading text, and
  may ignore it — exactly as it may ignore what the user wrote. One task does
  not get to drive another.
- **Notes carry news, folders carry data.** A note is one short line. Tasks
  that need to hand over real output share a folder, which already works; the
  note says *there is something new there*.
- **The tool is opt-in.** `notes` is not in the default toolset. On by default
  would mean every task can write into every other task's memory from the day
  it is created.

## Out of scope

- Ordering. "A, then B" is steps inside one task, which already works. This
  slice is for independent tasks nudging each other.
- Replies, threads, addressing more than one task at a time, delivery receipts.
- Notes that trigger a run. That is where loops live, and it is a scheduling
  change, not a messaging one.
- Reaching tasks outside this daemon's tasks folder.

## Vocabulary

No fourth word. The user already knows that a task keeps a journal and that
`poieo note` puts a line in it. A task doing the same thing is the same idea.

In the journal a note reads as its sender:

```
- 2026-08-23 03:00 · task     [build-docs] rebuilt the docs; 30 links changed
```

Words that must not appear in the interface: *message, queue, inbox, deliver,
cursor, unread*. The prompt says **new since you last worked**, which is what
it means without naming the machinery.

## What a task sees

```
You are working on check-links, in ~/src/thing.

New since you last worked:
- [build-docs] rebuilt the docs; 30 links changed
- (you) ignore external links

What you did before that:
- checked 12 links, all fine
- nothing worth doing
```

Both sections come from one file. The first is complete; the second is the
bounded tail. When there is nothing new the first section says so plainly
rather than being absent, because "no news" is information.

## The tool

One tool, in a `notes` toolset a task opts into:

**`tell(task, message)`** — leave one line in another task's journal.

- The recipient is named by the same short name the user types for
  `poieo note`. An unknown name is a tool error the model can read and correct,
  listing the names that do exist.
- A task cannot write to its own journal with it; that is what its own run
  record is for.
- The message is one line, capped like every other journal line.
- The sender is stamped by poieo, not supplied by the model, so a note cannot
  claim to be from someone else.
- Who exists is in the system prompt, so the model does not have to guess or
  call a second tool to find out.

## Delivery rules

| | |
|---|---|
| **when the bookmark moves** | after a run that completed or found nothing to do — **not** after a failure. A failed run saw the note but cannot be said to have handled it, and repeating a note is recoverable where losing one is not. |
| **a backlog too big for one prompt** | delivered oldest first, in batches, and the bookmark moves only as far as what was shown. The rest arrives next run, with a line saying how many are waiting. Nothing is ever dropped. |
| **a task that has never run** | has no bookmark, so everything is new. Correct on its own terms. |
| **a hand-edited journal** | still works. The bookmark is a line in the file, so a person can move it by editing, and the whole thing degrades to "read it all". |
| **an unreachable journal** | forgetting beats failing, as today: the run proceeds with no memory and the failure is logged. |

## Interaction with isolation

A journal lives beside its task file, outside any task's folder. A task running
isolated can therefore reach, through `tell`, something outside the fence.

This is deliberate and worth stating rather than discovering. What crosses is
not arbitrary: **one line, length-capped, into a named file, with the sender
stamped by poieo.** That is a controlled channel, not a hole — the same shape
as a task's own run record, which already crosses it. What an isolated task
still cannot do is read or write another task's files.

A task that should not talk to anything simply does not take the `notes`
toolset, which is why it is opt-in.

## The risk that remains

Two tasks can now confuse each other. A note that is wrong, or stale, or based
on a run that later failed, is read as plainly as a correct one. Nothing here
verifies content — it is the same trust the user already extends when they type
`poieo note`.

What the design does guarantee is narrower and worth being precise about: a
note that was written **will be seen once**, and a task's own memory cannot be
crowded out by how much it is being told.

## Testing

- **The loss test is the point of the slice.** A journal long past the display
  bound, with a note appended after the task's last entry: that note must
  appear. Written first.
- The same for a user's note, which is the latent bug this fixes.
- A failed run leaves the bookmark where it was, so the note arrives again.
- A backlog larger than one batch drains across runs and drops nothing.
- Unknown recipient, self-addressed, and over-long messages are tool errors the
  model can read, not crashes.
- The sender stamp cannot be forged from the message argument.
- A task without the `notes` toolset has no such tool at all.
- Every existing journal test stays green: a task with no notes must read
  exactly as it does today.

## Implementation split

One plan, four tasks: reading the journal in two parts; the `tell` tool and its
toolset; the roster in the system prompt; docs and a worked example of two
tasks nudging each other.
