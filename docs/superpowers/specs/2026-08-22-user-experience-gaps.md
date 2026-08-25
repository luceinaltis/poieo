# What Is Still Missing for the User

**Date:** 2026-08-22
**Status:** A and B approved and specified; C and D still proposals
**Relates to:** DESIGN.md roadmap steps 4 and 5

The roadmap answers *what did it do* (observation) and *do I want it*
(the morning review). This document lists what a person using poieo every day
still would not have once both ship, ranked by how much it costs them.

Each candidate names the user's problem first, the design second. None of them
adds a node type or a provider — they are all about the experience around the
machinery that already exists.

---

## A and B — specified elsewhere

The first two candidates have graduated into their own design:
**`2026-08-22-task-cards-design.md`**.

- **A — a task is one file.** A name, a folder, and a prompt; everything else
  defaulted. The card the web board will edit.
- **B — a review that talks back.** Accept and discard carry an optional note;
  each task keeps a journal of what it did and what the user said, and reads it
  before every run.

They shipped as one design because B is a few keys on top of A. What follows
are the two that remain open.

---

## C. Say why it stopped, in words, and stop repeating it

**The problem.** `on_error` defaults to `continue`, which is right for a flake
and wrong for everything else. Ollama not running at 2am produces four hundred
identical failed runs and a wall of red at 8am. The user's first question —
*why?* — is answered today by a stack trace in a log file.

**The design.** Two moves, both small.

1. Failures are classified into a handful of user-level causes, each with one
   suggested action: *the model could not be reached* (is Ollama running?),
   *ran out of turns*, *a command was blocked*, *the folder changed underneath
   it*. The plain sentence is what the card shows; the trace stays in the log
   for whoever wants it.
2. **A task that fails the same way N times in a row pauses itself** and says
   so. Staying up is the default (principle 5), but staying up while failing
   identically is not resilience, it is noise.

`poieo check` already probes every declared endpoint — the diagnosis mostly
exists, it just never reaches the user.

---

## D. Presence while nobody is looking, and a ceiling

**The problem.** The product is resident and the user is asleep. Everything it
knows is behind a browser tab they have to remember to open. And a cloud-bound
task can spend all night; token usage is recorded, but nothing stops it.

**The design.**

- **A ceiling per task** — tokens, spend, or wall-clock per night. Reaching it
  **pauses** the task (it is not a failure), and the card says so.
- **A morning digest** — one screen, and the same thing as one file:
  `3 tasks · 8 works · 2 waiting for you · +61 / -22`. The file matters because
  it is what a notifier, a webhook, or a shell prompt can read without poieo
  inventing a notification system.

Both stay inside the non-goals: no service, no auth, no accounts — one machine,
one person, files.

---

## Suggested order

1. **A + B** — now `2026-08-22-task-cards-design.md`, waiting on the checkpoint
   backend.
2. **C** — independent of everything else, small, and the fastest trust win.
   Can land beside the checkpoint work without touching it.
3. **D** — after the board exists, since the digest is the board summarised.
