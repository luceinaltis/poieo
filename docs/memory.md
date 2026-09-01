# Memory — what a project keeps

`src/poieo/memory/`, `src/poieo/learn.py`, `src/poieo/strength.py`, `src/poieo/blob.py`

A card's journal is short-term on purpose — old lines age out of the prompt. The
memory is the long-term half: a page every run reads, and the entries a run may
earn.

**One database per project, and it *is* the memory.** `memory/longterm.sqlite3`
holds the page, every entry, and the history of every change to either. Nothing
holds a second copy, so nothing can drift out of step with it — and nothing may
be lost by throwing it away, which is why a shape change here means *migrate*,
never *rebuild*. Two projects on one machine never see each other's memory: the
file lives inside the project, and the nearest `poieo.yaml` says which project
that is.

**The whole opt-in is the existence of that file.** No file, no trace of the
feature — not even an empty header in a prompt. A signal that switches itself on
is not consent, which is why journals live *beside* it: they arrive on their own
the first time a card runs.

What a person loses by this, git used to give for free — an editor, `git log`, a
reviewable diff, `grep`. The history table answers the second; `poieo memory`
answers the rest.

## The words

One name per thing. Each is fixed by two answers — **when it reaches a prompt**,
and **who may write it** — and every difference between them is one of those two.

| word | is | reaches a prompt | written by |
|---|---|---|---|
| **journal** | one card's running account of its own work | every run of that card; the oldest lines age out | the harness, every run |
| **page** | the one constitution a project runs under | every run of every card, whole and first | a person only |
| **entry** | one durable statement a run earned | only when `recall()` picks it for this card | a person, or the pass proposing and the harness writing |
| **piece** | the part of an entry retrieval matches on | never on its own; it is how its entry is found | with the entry, always |
| **record** | the full account of one run | never a card's; it is what the pass *reads* | the harness, once per run |
| **strength** | how much a connection has actually helped | never; it only reorders entries | reinforcement, from records |
| **blob** | the bytes an entry was written against | never | the harness, when an entry is anchored |

An entry has exactly **one** piece today. The split is not speculation about a
feature: an entry too long to fit the budget can never be shown whole, and when
one exists, cutting it is the only way it reaches a prompt at all. Putting the
seam in now costs a column; putting it in later costs the schema.

**Set aside** is the verb and `superseded_by` is what it writes — one act, and
the column is the record of it, not a second thing. Two writers, named in every
line of history: a **person**, and the **pass**. A third would cost a reason.

**Only two questions are settled by the words an entry shares**, and both weigh
the entry's *body* alone: which entries a card is shown (`recall()`), and whether
an entry did real work in a run (`used_in()`). Scope and anchors match names and
paths exactly; the page is never matched at all, because it is never chosen.

### What counts as one word

`words()` reduces each word to its **shape** before either question is asked,
so `feeds` and `feed` are one word — an entry missed over a plural is then
also miscounted as "shown and never used", a double cost.

The shaping is **plurals and nothing else**, by suffix, not a stemmer: verb
endings and real stemming both lose precision over tens of documents, where
one wrong match is a whole wrong entry in a prompt. Both sides of a comparison
are shaped by the same function, so a shape only has to be consistent, never
right; a stem under four letters or landing on a glue word is refused. Shaping
happens in **one** place, and `pieces` stores the shape beside the text, so
narrowing and scoring can never disagree.

The machinery names stay in this package and on this page. `poieo memory` says
different words on purpose, and neither list is the other's mistake:

| machinery | what a person is told |
|---|---|
| `recall()` | lookup |
| entries | learned |
| `doubts()` | second look |
| accounting | kept in mind |
| the page | *What this project always requires* |

## The files

```
memory/
  shortterm/<slug>.md       one journal per card            → tasks.md
  longterm.sqlite3          ← the opt-in, and the memory itself
    entries                 what this project has learned
    pieces                  what retrieval matches on
    links                   who names whom, so a neighbour is fetched not found
    page                    the one page in front of every run
    history                 every write, and who wrote it
    pieces_fts              derived; dropped and rebuilt without being asked
    pieces_text_fts         derived; Unicode word search for a person
  cache/                    derived; delete it freely
    strength.json           how strong each connection is
    embeddings.sqlite3      entry vectors, keyed by model and body digest
    blobs/                  copies of what entries were written against
    learning.jsonl          what every pass did
runs/results/<run_id>.json  the full record of one run
runs/asking/<card>.json     a question that run left for you, until it is answered
```

Truth is `longterm.sqlite3`, and only what is *inside* it is truth: `pieces_fts`
is rebuilt without being asked, and everything under `cache/` may be deleted
outright. Nothing is ever true because something derived says so.

Losing that one file loses the memory, which is the price of not keeping two.
`poieo memory` reads it back out; export is what makes a copy worth having.

## The modules

| module | is |
|---|---|
| `entries.py` | where the memory is kept: schema, the one write door, history, the page, load-time checks |
| `index.py` | a derived lookup over the pieces, dropped and rebuilt without being asked |
| `browse.py` | the bounded graph, entry detail and a person's word search |
| `semantic.py` | meaning search and its disposable model-specific vectors |
| `ask.py` | hybrid shortlist, evidence-only answer and citation checking |
| `recall.py` | choosing what a card is shown, and assembling the block |
| `results.py` | the full record every run leaves behind |
| `upkeep.py` | what the memory would like a person to look at |
| `learn.py` | the pass that reads records and proposes entries |
| `strength.py` | how strong each connection is |
| `blob.py` | kept copies of the bytes an entry was written against |

`memory/__init__` re-exports what the rest of poieo asks for. The ranking
function is deliberately *not* exported: reaching for it from outside means
reaching past `read_memory()`, which is the answer everything else wants.

## An entry

```python
write_entry(
    project, "batch-cap",
    "One durable statement, mentioning [[another-entry]] freely.",
    frontmatter({
        "scope": ["global"],           # global, a card slug, or a path prefix
        "anchors": ["src/poieo/card.py::read_journal"],  # path, or path::symbol — never line numbers
        "source": ["20260824T031400-a1b2c3d4"],          # the runs that taught it
        "valid_from": "2026-08-24",
        "superseded_by": None,         # set this instead of deleting
        "links": {
            "depends_on": ["batch-cap"],       # what this needs to stay true
            "contradicts": ["old-batch-cap"],  # a standing question for a person
        },
        "sealed": {"src/poieo/card.py": "<sha256>"},
    }),
    writer="person",
)
```

`write_entry` is the only door, and everything goes through it — a person, and
the pass. It refuses a slug that is not `^[a-z0-9][a-z0-9-]*$`, which is the
fence a slug that could escape a folder never got past; `extra="forbid"` on the
frontmatter means an unrecognised key is a typo rather than a silently ignored
line; and it writes the line of history that says who did this and what changed.
`examples/remembering/seed.py` is a whole memory written this way.

`check_memory()` runs at daemon load and validates typed claims across the whole
memory — a `depends_on`, `contradicts` or `superseded_by` naming nothing that
exists is a startup error. **Prose `[[mentions]]` are deliberately not checked**:
a mention of an entry that does not exist yet marks something worth writing.

## The shape, and moving it

`SCHEMA_VERSION` is stored in the database. Opening one written by an older poieo
migrates the rows forward, in order, before anything reads them; opening one from
a *newer* poieo refuses rather than guessing, because a wrong guess here is the
only copy. There is no "delete it and rebuild" — that was the old derived index's
privilege, and it went when the file became the truth.

Mid-residency the rule flips: `readable_entries()` skips a malformed entry with a
warning, because a run with less in mind beats no run at all.

## What a run is shown

`read_memory(project_dir, task)` builds one block:

```
What this project always requires:      the page, whole, first, always
<the page, comments stripped>

What earlier work here has learned:     the entries this card earned
<entry bodies, best first, cut on whole-entry boundaries>
```

The page comes first and whole so the stable part of the prompt stays stable, and
it never competes with entries for room — `ENTRIES_BUDGET` (4 000 characters)
bounds only what follows it. Markdown comments are stripped from the page before
any prompt sees it, which is what lets `poieo init` start a memory whose page
is all comments and costs a project nothing.

### Ranking

`recall()`:

1. **filter** — entries not set aside, whose `scope` covers this card (the word
   `global`, the card's slug, or a path that contains its folder)
2. **narrow** — the lookup proposes candidates for the seed shapes (the card's
   name, prompt and folder, shaped the same way the pieces were)
3. **score** — shared distinctive words, plus `_ANCHOR_BOOST` (1 000) if the
   entry *anchors* where the card works. An anchored entry is relevant by where
   it points, not by the words it shares, so it is added to the pool directly
   rather than depending on the lookup finding a shared word
4. **associate** — a neighbour of a chosen entry has no score of its own to argue
   with; its claim is its seed's, divided by the seed's rank and multiplied by
   how strong that connection is. A **second** hop is taken only across a strong
   connection, so with nothing reinforced one hop means one hop
5. **fill** — entries in scope that the card matched nothing in, newest first,
   behind everything above. They seed no associations of their own: a claim
   divided by rank has to start from a claim
6. **cut** — best first, on whole-entry boundaries. Half a lesson is worse than
   none, and an entry too big for the budget loses only its own place: skipping
   it leaves the room to whoever ranks below, where stopping at it hid them all

### Who is in the room, and who is merely first

**Scope decides admission. Matching decides the order. The budget decides who
is cut.** Sharing a word is *evidence*, not a ticket — dropping unmatched
in-scope entries used to leave most of the budget empty while lessons went
unshown.

Two things are not room-dependent, and both stay:

- **Scope** is the author saying who an entry is for. An entry scoped to another
  card is not shown however much room there is.
- **`contradicts` is a veto.** Putting an entry and the one disputing it in front
  of a model together is the thing that field exists to prevent, and having space
  is not a reason to. Step 5 skips both sides of a standing disagreement.

### When meaning-ranking earns its place

This section is about **autonomous recall into a run**, not a person's search
on the board. The board may compare meaning because it changes what the person
sees, never what a task is shown on its own.

Nothing here compares meaning — the whole of it is set intersection over shaped
words. That is deliberate, and the condition for revisiting it is written down
rather than left to taste:

**When a project's entries start filling `ENTRIES_BUDGET`.** Below that, ranking
decides only what order things are read in, because everything in scope is shown
either way; a hybrid of word-matching and meaning-matching would be a change with
no observable effect and no way to verify it. Above it, ranking decides who is
cut, and *that* is measurable — does the order put the right entries above the
line? At roughly a hundred characters an entry, the crossing is near forty.

There is a second reason waiting at the same place, and it is arithmetic rather
than judgement. Ranking by shared words means scoring **every** entry the lookup
matched, so a card whose words are common to the project scores the whole memory:
4 ms at fifty entries, 130 ms at five thousand, 1.8 s at fifty thousand. Letting
the lookup rank and return only its best would make that flat — and the lookup
already has `bm25()` sitting unused. Neither reason binds yet; both come due
together.

The notes for what to build then: hybrid retrieval beats either channel alone
on agent-memory benchmarks, fused by rank (the units do not compare) with the
word channel weighted higher. Until the budget fills, none of that has
anything to decide.

`connected()` decides who arrives beside an entry: `[[mentions]]` count in
**either** direction (nearness is symmetric), `depends_on` **forward only** (what
you chose needs what it leans on, not the reverse), and `contradicts` is a
**veto** — "this disputes [[x]]" is an ordinary way to write a disagreement, and
the mention inside it must not smuggle the disputed entry into a prompt.

## What a person searches on the board

The board has three explicit modes. **Words** searches the visible memory slug
and the raw piece text with Unicode FTS and a Unicode substring fallback; it
does not reuse the ASCII shape whose narrower job is autonomous recall.
**Meaning** embeds the query and entry
bodies in the model named by `memory_embedder`, compares cosine similarity, and
keeps vectors only under `memory/cache/`. A changed body, model or endpoint
fingerprint misses that cache and is embedded again. The cache is disposable:
a damaged SQLite file is removed and rebuilt from the entry bodies.
That first miss sends each entry body to the configured embedding endpoint;
choose that role with the same privacy care as any model that reads a prompt.

**Ask** takes both ranked lists and fuses ranks, with the word channel weighted
twice. The model named by `memory_searcher` receives only that shortlist, no
tools, and must cite supplied slugs as `[[slug]]`; citations to anything else
are removed. If meaning search fails, the response says it used words only.
Queries and answers are not persisted.

Similarity is never topology. The graph draws `mentions`, `depends_on`,
`contradicts` and `superseded_by`, plus learned strength on those existing
connections. A similar result may glow; it never earns a line.
Directional relationships have arrowheads, and the selected entry lists their
targets and its recorded history beside the graph.
The initial paint caps both memories and connections; its response says when
either was shortened, while search still reaches every entry.

### Strength

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
next write. Delete `strength.json` and the project forgets which paths were strong,
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

A set-aside entry stays where it is. It is out of every prompt, and nothing
here moves or deletes it — the memory changes when a person changes it, and
the history says what it was before. **Nothing sweeps.**

## Keepsakes

`blob.py` keeps the exact bytes of each anchored file as the entry was written
against it, flat and content-addressed under `memory/cache/blobs/` (same content,
same name, one copy; written tmp+rename so a torn write cannot leave a wrong body
under a right name).

That is what makes a doubt mean *the content really differs* — a merely-touched
file raises nothing — and it keeps the original openable. Files over 8 MB are not
kept: hoarding is an anti-goal, and so is a night's work failing over a fat file.
A keepsake is a copy, never a meaning, so failing to keep one never blocks the
entry, and one that nothing references any more is let go after a grace long
enough for a person to restore the entry that named it.
