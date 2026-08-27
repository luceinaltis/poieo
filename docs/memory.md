# Memory — what a project keeps

`src/poieo/memory/`, `src/poieo/learn.py`, `src/poieo/strength.py`, `src/poieo/blob.py`

A card's journal is short-term on purpose — old lines age out of the prompt. The
memory is the long-term half: a page every run reads, and a folder of entries a
run may earn.

**The whole opt-in is the existence of `memory/longterm/`.** No folder, no trace
of the feature — not even an empty header in a prompt. A signal that switches
itself on is not consent, which is why journals live *beside* that folder rather
than inside it: they arrive on their own the first time a card runs.

## The files

```
memory/
  shortterm/<slug>.md       one journal per card            → tasks.md
  longterm/                 ← the opt-in
    constitution.md         one page, in front of every run
    facts/<slug>.md         one file per learned entry
    attic/                  entries at rest
  cache/                    derived; delete it freely
    index.sqlite3           the lookup
    strength.json           how worn each connection is
    blobs/                  copies of what entries were written against
    learning.jsonl          what every pass did
runs/results/<run_id>.json  the full record of one run
```

Truth is markdown under git. Everything under `cache/` is derived and rebuilt
without being asked; nothing is ever true because the cache says so.

## The modules

| module | is |
|---|---|
| `facts.py` | the files: parsing, frontmatter, the page, load-time checks |
| `index.py` | a derived sqlite/FTS lookup over them |
| `recall.py` | choosing what a card is shown, and assembling the block |
| `results.py` | the full record every run leaves behind |
| `upkeep.py` | what the memory would like a person to look at |
| `learn.py` | the pass that reads records and proposes entries |
| `strength.py` | how worn each connection is |
| `blob.py` | kept copies of the bytes an entry was written against |

`memory/__init__` re-exports what the rest of poieo asks for. The ranking
function is deliberately *not* exported: reaching for it from outside means
reaching past `read_memory()`, which is the answer everything else wants.

## An entry

```markdown
---
scope: ["global"]                  # global, a card slug, or a path prefix
anchors: ["src/poieo/task.py::read_journal"]   # path, or path::symbol — never line numbers
source: ["20260824T031400-a1b2c3d4"]           # the runs that taught it
valid_from: 2026-08-24
superseded_by: null                # set this instead of deleting
links:
  depends_on: [batch-cap]          # what this needs to stay true
  contradicts: [old-batch-cap]     # a standing question for a person
sealed: {"src/poieo/task.py": "<sha256>"}
---
One durable statement, mentioning [[another-entry]] freely.
```

The slug is the filename. `extra="forbid"` on the frontmatter means an
unrecognised key is a typo, not a silently ignored line.

`check_memory()` runs at daemon load and validates typed claims across the whole
folder — a `depends_on`, `contradicts` or `superseded_by` naming nothing that
exists is a startup error. Attic entries count as existing, or "move the file
back" would not be true. **Prose `[[mentions]]` are deliberately not checked**: a
mention of an entry that does not exist yet marks something worth writing.

Mid-residency the rule flips: `readable_facts()` skips a malformed entry with a
warning, because a run with less in mind beats no run at all.

## What a run is shown

`read_memory(project_dir, task)` builds one block:

```
What this project always requires:      the page, whole, first, always
<constitution.md, comments stripped>

What earlier work here has learned:     the entries this card earned
<entry bodies, best first, cut on whole-entry boundaries>
```

The page comes first and whole so the stable part of the prompt stays stable, and
it never competes with entries for room — `FACTS_BUDGET` (4 000 characters)
bounds only what follows it. Markdown comments are stripped from the page before
any prompt sees it, which is what lets `poieo init` write an empty
`constitution.md` that costs a project nothing.

### Ranking

`recall()`:

1. **filter** — entries not set aside, whose `scope` covers this card (the word
   `global`, the card's slug, or a path that contains its folder)
2. **narrow** — the sqlite index proposes candidates for the seed words (the
   card's name, prompt and folder)
3. **score** — shared distinctive words, plus `_ANCHOR_BOOST` (1 000) if the
   entry *anchors* where the card works. An anchored entry is relevant by where
   it points, not by the words it shares, so it is added to the pool directly
   rather than depending on the index finding a shared word
4. **associate** — a neighbour of a chosen entry has no score of its own to argue
   with; its claim is its seed's, divided by the seed's rank and multiplied by
   how worn that connection is. A **second** hop is taken only across a worn
   connection, so with no wear anywhere one hop means one hop
5. **cut** — best first, on whole-entry boundaries. Half a lesson is worse than
   none

`connected()` decides who arrives beside an entry: `[[mentions]]` count in
**either** direction (nearness is symmetric), `depends_on` **forward only** (what
you chose needs what it leans on, not the reverse), and `contradicts` is a
**veto** — "this disputes [[x]]" is an ordinary way to write a disagreement, and
the mention inside it must not smuggle the disputed entry into a prompt.

### Wear

`strength.py` holds *how often a connection actually helped* — runtime emphasis,
never meaning. What connects to what stays a judgment in markdown.

A pair is reinforced when two connected entries both did real work in a run that
succeeded, judged by `used_in()`: the entry's distinctive words surface in what
the run itself produced. It is a behavioural stand-in until a serving stack can
report attention, and it is deliberately the *same* judgment the accounting uses,
so the two can never disagree.

It cannot run away: every weight halves every 30 days untouched (applied when
read), no entry's connections may total more than `FAN_CAP` (an entry connected
to everything has weak claims on each), and pairs below a floor are dropped on the
next write. Delete `strength.json` and the project forgets which paths were worn,
relearns them by working, and loses not one word of meaning — so nothing in that
module is ever worth failing anything over.

## Run records

`results.py` writes one JSON file per run to `runs/results/<run_id>.json`, once,
never rewritten. It sits **beside** the event stream the same run wrote to
`runs/events/` — two halves of one account, the stream as it happened and what
was left when it stopped — and shares its run id, so an entry's `source:` can
name the run that taught it.

The record is unclipped where the run log clips. It carries the card's slug, the
run's outputs, the closing line as `summary`, and `shown` — which entries the
project had in mind, recomputed at record time by the same selection that built
the run's block. `shown` is emphasis-grade: failing to compute it costs the field
and not the record, let alone the run. **The harness writes these, never the
model**: there is no tool for it, so nothing depends on a model remembering to
remember.

## The learning pass

`poieo learn tasks/` by hand, or `learn: 1d` in the config for the daemon to run
one while nothing else is.

```
unread records → one completion → validate → write
```

**The model proposes; the harness writes.** That order is the whole safety story,
because the distiller is the most dangerous writer in the system:

- `source:` is stamped by the harness — whatever the model claimed is cut to the
  records actually shown, and nothing surviving means all of them
- a slug must match `^[a-z0-9][a-z0-9-]*$`, which doubles as the fence: a slug
  that could escape the folder cannot pass
- a proposal naming an existing slug is dropped — **a pass never overwrites**
- links are settled to a fixpoint: dropping one entry can strand another that
  pointed at it, and a dangling claim would trip the next load
- the only verbs are *write a new entry* and *set one aside*. Nothing is deleted,
  nothing is overwritten, and **the page is never touched** — a pass may
  *suggest* one line for it, which is recorded and shown, and only a person ever
  edits that page

The bookmark — the last record a successful pass reached — lives in
`learning.jsonl` and moves only on success, so a failed pass **rereads** rather
than skips. Repeating is recoverable; losing is not. `PASS_CAP = 20` records per
pass, and what does not fit arrives next pass.

An empty answer is the right answer most nights, and the prompt says so.

## Upkeep

Everything in `upkeep.py` is computed from the files at read time — no queue, no
stored counter, nothing written. **Nothing anywhere acts on any of it.** Numbers
inform; people and passes decide.

`poieo memory` reports:

- **disagreements** — `contradicts` pairs where both sides still stand. Never
  resolved by a machine
- **second look** (`doubts()`) — an entry leaning on one that was set aside; an
  anchor whose target is gone; an anchor whose target no longer matches what the
  entry was written against. The clearing gesture is always the same: *edit the
  entry after looking*, and the flag goes, because the entry's mtime passes the
  file's
- **accounting** — over the last 50 run records, how many runs used what they
  were shown, and any entry shown `UNUSED_FLOOR` times or more without ever being
  used. Dead weight, for a person to look at

The same doubts are shown to the next learning pass, which is free to retire an
entry with its ordinary set-aside.

Entries set aside long enough, and named by nothing, move **whole** to
`memory/attic/`: out of every prompt and every count, restored by moving the file
back, deleted never.

## Keepsakes

`blob.py` keeps the exact bytes of each anchored file as the entry was written
against it, flat and content-addressed under `memory/cache/blobs/` (same content,
same name, one copy; written tmp+rename so a torn write cannot leave a wrong body
under a right name).

That is what makes a doubt mean *the content really differs* — a merely-touched
file raises nothing — and it keeps the original openable. Files over 8 MB are not
kept: hoarding is an anti-goal, and so is a night's work failing over a fat file.
A keepsake is a copy, never a meaning, so failing to keep one never blocks the
entry, and one that nothing references any more is let go after the attic's
grace.
