# Project Memory Design

**Date:** 2026-08-24
**Status:** Approved for planning
**Roadmap:** a long memory

## Goal

What a project learns must survive the run that learned it. And anything the
project claims to remember must be traceable to the work that taught it.

Today a task's only memory is its journal, and the journal is deliberately
short-term: recent lines reach the prompt, older ones age out. That is right
for a record of activity and wrong for knowledge. A lesson learned a hundred
runs ago — *this API rejects batch sizes over 50; the flaky test is the
fixture, not the code* — is exactly as true tonight as the day it was learned,
and tonight's run cannot see it.

This design gives the project a memory: a place where what has been learned
stays until it is deliberately changed, is read by every task before it works,
and can always be followed back to the run that taught it.

## Where this sits

poieo already has two kinds of record, and this adds a third. The boundaries
matter more than the machinery:

| | belongs to | written by | ages out? |
|---|---|---|---|
| **journal** | one task | the harness and the user | yes — recent lines reach the prompt, old ones fall away |
| **memory** | the whole project | the user (for now — see the road beyond P1) | no — an entry stays until superseded |
| **record of work** | one run | the harness | never — append-only, kept whole |

The user-facing sentence is short: *a task keeps a journal of what it did
lately; the project keeps a memory of what it has learned. Journal lines age
out; a memory stays until you change it.*

Internally these are three tiers, and the spec will use those names —
**Tier 0** (a constitution: one page always in front of every run), **Tier 1**
(facts: distilled knowledge, retrieved when relevant), **Tier 2** (episodes:
the full record each run leaves behind). The tier words are for this document
and the code. They never reach a prompt, a card, or the CLI.

## The one idea

**Distillation is storage — but never unsourced.** A memory system that keeps
raw transcripts drowns; one that keeps only conclusions confabulates. So the
project stores the distilled form (one page of rules, one file per learned
fact) and requires every distilled entry to point at its origin: a fact names
the episodes that taught it, an episode names the run that produced it, and
the run's full event log is already on disk. Ask of any remembered line
"says who?" and the answer is a file you can open.

The second half of the idea is a separation the rest of the design keeps
falling out of: **truth lives in markdown under git; anything a machine
derives lives under `.poieo/` and can be deleted without loss.** The
constitution and the facts are files a person edits, reviews, and versions —
the human-audited layer. The search index is derived from those files and
rebuilt from them at any time; episodes are runtime records like run logs.
Nothing human-audited and nothing machine-derived ever share a layer, so a
`git diff` of the memory is always a diff of meaning, never of counters.

This is why DESIGN.md's non-goal changes from "no database" to "no database
of record." The index is a database in the way a thumbnail cache is a copy of
your photos: deleting it loses nothing, and nothing is ever true *because*
the index says so.

## Decisions already made (with the user)

- **One memory per project, and the project is the tasks folder.** Task
  separation is a filter at read time, never a second store. Lessons cross
  tasks — that is most of their value — and contradictions can only be seen
  where everything is in one place.
- **Episodes are written by the harness, not by the model.** Every run of a
  task leaves a full record automatically. The model does not decide what is
  worth recording, cannot forget to record, and has no tool to write memory
  with — in this slice the model cannot author memory at all.
- **Nobody writes the distilled layers casually.** In this slice the
  constitution and the facts are written by the user, in an editor, under
  git. The machine author — a compaction pass that distills episodes into
  facts — is a later slice, and even then the constitution stays behind a
  human review, because a page loaded into every run has the largest blast
  radius a wrong sentence can have.
- **Demote before delete.** A wrong fact is marked superseded and set aside,
  not erased. Retrieval stops showing it; the file, and the trail back to
  what taught it, remain. Judgment calls — a model's or a person's — never
  drive an irreversible action directly.
- **Measured from day one.** The memory must be able to answer "what would
  this task see, and why?" from its first release (`poieo memory`), because
  the only benchmark that matters is this project's own workload.
- **Zero configuration.** A project without a `memory/` folder behaves
  byte-for-byte as today. Creating the folder is the whole opt-in.

## Storage model

The project is the tasks folder — the directory holding the cards. That is
already where journals live and where `.poieo/` lands, so memory is
discoverable from a single card with no configuration.

The human-audited layer, versioned with git:

```
<tasks folder>/
  memory/
    constitution.md        one page, in front of every run, whole
    facts/<slug>.md        one file per learned fact
  <slug>.yaml, <slug>.md   cards and journals, unchanged
```

`memory/` is a subdirectory because the folder root belongs to cards and
journals: a card named `memory.yaml` would collide with a root-level file,
and a subdirectory cannot collide with anything the task loader reads. A
fact's identity is its filename stem, the same rule task slugs follow.

The machine layer, under the already-gitignored `.poieo/`:

```
<tasks folder>/.poieo/
  episodes/<run_id>.json   one per run, append-only, never rewritten
  memory.sqlite3           derived index; delete it and it is rebuilt
  runs/<run_id>.jsonl      existing event log, unchanged
```

Memory artifacts anchor to the tasks folder's own `.poieo/`, always — even
when a daemon config points the run-log store elsewhere. One project, one
memory, regardless of how many configs drive it; the episode carries the
run id, so it joins the run log wherever that lives.

### The constitution

One markdown page, injected whole into every run of every task in the
project. Because it is always present, it is the most expensive real estate
in the system, and admission is zero-sum: to add a rule, ask the four
questions —

1. Does it apply to every task, not just some?
2. Is violating it expensive?
3. Would retrieval fail to bring it up when needed? (Prohibitions are the
   canonical case: nothing in a task's prompt searches for what it must not
   do.)
4. Is it invisible in the code itself?

Only a yes to all four earns the page. Design-document prose, in-progress
state, and anything derivable by reading the code stay out. These questions
ship as a comment at the top of the authored page, because the page's editor
is the person who needs them.

The constitution can be wrong. Correction is a git revert away, and the page
is re-read every run, so an edit takes effect on the next one — poieo's
standing promise, no reload.

### A fact

One file, one fact, prose body, small frontmatter:

```
---
scope: [global]              # or task slugs / path prefixes — a filter, never a wall
anchors: []                  # "path" or "path::symbol" the fact is about
source: []                   # run ids of the episodes that taught it; empty = human-authored
valid_from: 2026-08-24       # optional: when the fact became true
superseded_by: null          # a fact slug; set this instead of deleting
---
The API rejects batch sizes over 50; the importer learned this on 08-21.
```

- **Scope** narrows retrieval to where the fact applies. It is a filter over
  one store; it is never a second store.
- **Anchors** name the code a fact is about. No line numbers — they rot
  fastest, and this slice has no revalidation to catch the rot. In this
  slice anchors serve retrieval (a fact anchored where a task works ranks
  higher); anchor-triggered revalidation is a later slice.
- **Source** is the traceability requirement made concrete. An empty list
  means a person wrote it, which is its own kind of source.
- **Time**: git already records when every line was written, for free, so
  the file carries only event time — when the fact became true, if that
  differs from when it was recorded.
- **Superseded** is the demotion. The file stays; retrieval skips it. Links
  written as `[[fact-slug]]` are permitted in the body and are inert in this
  slice — they become edges when the graph arrives.

### An episode

Every run of a task writes one episode: run id, task, status, error, steps,
path, token usage, timestamps — and the summary and per-node outputs
**unclipped**. The existing run log clips event text for display; the episode
is the version that does not, because it is what distillation will one day
read. It is honest about what it is: result-grade, not transcript-grade. The
full turn-by-turn record stays in `runs/<run_id>.jsonl`, one join away.

Runs of a bare graph — no task card — write no episode, exactly as they keep
no journal. Memory is a property of projects, and an ad-hoc graph has none.

## Who writes what, who reads what

Writing, in this slice:

| layer | author |
|---|---|
| constitution | the user, in an editor, under git |
| facts | the user, in an editor, under git |
| episodes | the harness, automatically, at the end of every task run |
| index | the machine, derived, rebuilt whenever the facts change |

Reading: before every run, the harness composes one block — the constitution
first and whole, then the facts retrieval chose for this task, best first,
cut at a budget on whole-fact boundaries. Retrieval seeds from what the task
is (name, prompt, folder), keeps facts whose scope covers the task, and
ranks anchored-where-you-work above merely-similar. The block reaches the
prompt the same way the journal does, on both the daemon path and the
one-shot CLI path. The constitution's position is fixed — always first,
before anything retrieved — so the stable part of the prompt stays stable.

The prompt does not cite sources. Traceability is a property of storage —
the place a person goes to ask "says who?" — not prompt furniture; every
token injected is a token of attention spent, and the model needs the
lesson, not the bibliography.

One edge is left open deliberately, and stated rather than discovered: a
task whose working folder contains the tasks folder can reach `memory/` with
its file tools. That is the same standing exposure journals and cards
already have — it comes from the user's choice of folder, and this slice
opens no new channel. The fence for a task that must not touch memory is the
same as for one that must not touch journals: give it a folder of its own.

## Out of scope (deferred, with their guardrails kept)

Each of these is a later slice. What is *not* deferred is the rule that
travels with it — those hold from day one:

- **The knowledge graph** (typed links between facts, one-hop expansion at
  retrieval). Deferred; `[[links]]` in fact bodies are already legal and
  simply inert. *Kept now:* similarity is never stored as a link. A link is
  a judgment with a type and a reason; a similarity score is a derived
  number, and the pairs it ranks highest include exact contradictions.
- **Sleep-time compaction** (a background pass distilling episodes into
  facts, merging duplicates, proposing supersessions). Deferred. *Kept now:*
  when it arrives, its conclusions are demotions and proposals, never
  deletions — and constitution changes stay behind a human review.
- **Associative retrieval** (spreading activation, learned edge weights).
  Deferred. *Kept now:* runtime statistics never live in the markdown. The
  human-audited layer stays a diff of meaning.
- **Files and images** (content-addressed blobs, caption-and-point).
  Deferred. *Kept now:* originals are never auto-injected into prompts;
  text describes, the original is fetched on demand.
- **Anchor revalidation** (a commit touching a fact's anchor queues the fact
  for re-checking; superseding a fact re-checks what depended on it).
  Deferred with the graph. *Kept now:* no deletion without a grace period,
  ever — demotion is the only fast path.
- **Per-task memories.** Not deferred — rejected. Scoping is a filter over
  one store. This line exists so nobody helpfully adds a second store later.
- Also out of this slice: an agent-facing memory tool of any kind,
  transcript-grade episodes, memory for ad-hoc graph runs, and retention
  sweeps of superseded facts (they stay, set aside, until a lifecycle slice
  gives them a grace period and an archive).

## Vocabulary

**Memory** is the word, and it names a place, not a mechanism — the same way
*journal* already does. The user's three words (task, work, change) stay
three; a memory, like a journal, is a file they can open.

In the interface: a project *has a memory*; a task *reads it before
working*; an entry was *learned* from a piece of work; a wrong entry is
*set aside*, not deleted. The one page of rules is the *constitution* — a
human word for a human-audited document.

Words that must not reach a prompt, a card, or CLI output: *tier, fact,
episode, retrieval, index, search, embedding, compaction, distill, anchor,
namespace, scope, frontmatter, SQLite, FTS, store, recall, knowledge base.*
This document uses them freely; they are machinery, and machinery does not
appear in the interface.

The injected block introduces itself in interface words: the constitution
under **"What this project always requires:"**, retrieved entries under
**"What earlier work here has learned:"**.

## Failure handling

| | |
|---|---|
| **no `memory/` folder** | nothing happens: no block, no input key, prompts byte-identical to a build without this feature. Silence, not an empty section — a project that never made a memory should see no trace of one. |
| **malformed fact file** | fails at load, naming the file — the fail-at-launch principle. A typo in frontmatter must not surface at 3am as a half-read memory. |
| **constitution over budget** | loads whole and warns. The page is the user's to trim; refusing to run over page length would make the memory a way to break the daemon. |
| **FTS5 missing from this Python build** | retrieval falls back to a plain scan over the same files — same results, slower, said once in the log, never an error. |
| **index missing, stale, or corrupt** | rebuilt silently from the facts. Derived means never asked about. |
| **episode write fails** | logged, and the run's result stands. Memory is not worth killing a night's work over — the same rule journals follow. |
| **superseded fact** | set aside: excluded from retrieval, file intact, trail intact. |
| **`--set memory=...` collides with the input key** | last writer wins, exactly as `--set journal=` does today. The names are shared deliberately: what the prompt sees is what the input carries. |

## The road beyond this slice

Each later phase is independently useful and none is presupposed by the
files this slice writes.

**The graph.** Facts gain typed links (`supersedes`, `caused_by`,
`depends_on`, `contradicts`, `relates_to`) — declared in the markdown as
`[[links]]` where a person can review them, weighted in the index where a
machine can learn them. A link type earns existence only when a mechanism
consumes it; unconsumed types merge into `relates_to`. Retrieval grows
one-hop expansion from its seeds.

**Sleep-time compaction.** A background pass reads episodes and proposes the
distilled layer: new facts, merges, supersessions. Routing follows blast
radius — mechanical selection can run on a local model, but what is
committed to memory is distilled by the best model bound, because a
compaction error poisons every later run and the write volume is tiny. In
poieo terms the compactor is a binding role (`roles: {compactor: ...}`) —
zero new code to point it at any provider — and the daemon already has three
seams for when it runs: a cron-triggered flow, an idle trigger, or a
daemon-owned background task beside the web server.

**Associative memory.** Retrieval becomes spreading activation over the
graph; edges strengthen when two entries prove useful *together* in a run
that *succeeded*, and decay otherwise. Strengthening lives entirely in the
index.

**Files and images.** Episodes gain content-addressed attachments; a
described image is remembered as its description plus a pointer, and pixels
load only on demand.

**Attention-informed utility.** Where the serving stack allows it, measure
which injected memories the model actually attended to, and let that inform
promotion and demotion. Until then, behavioral signals — what retrieval
brought that later work cited — stand in.

## Testing

- **The zero-configuration test is the point of the slice, written first.**
  A project without `memory/`: system prompt and run input byte-identical to
  today, on the daemon path and the CLI path both.
- The constitution reaches a run's prompt on both paths; an edit takes
  effect on the next run with no reload.
- A fact behind a matching scope arrives; a foreign scope does not; a
  superseded fact never does.
- The fallback and FTS5 return the same facts for the same project — proven
  by forcing the fallback in a test.
- The budget cuts on whole-fact boundaries and never touches the
  constitution.
- Every episode joins its run log by run id, and its summary is unclipped
  where the event log's copy is clipped.
- A failed run still writes its episode; a failed episode write still
  returns the run's result.
- Traceability, walked by hand in the worked example: pick an injected
  fact, follow `source` to an episode, follow the episode to the run log.

## Implementation split

One plan (F), five tasks, each landing alone: the episode record; the
memory page and its injection (with the zero-config invariant); retrieval
(index, scope, budget, fallback); `poieo memory` (read-only, shows what a
task would see and why); documentation and a worked example of a project
that remembers.
