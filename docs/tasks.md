# Tasks — the short form

`src/poieo/card.py`

A graph plus a binding plus a daemon entry is three files. When the work is *one
model, one folder, one instruction, on repeat*, a **task card** is one:

```yaml
name: keep improving poieo
folder: ~/code/poieo
prompt: |
  Find one thing worth fixing, fix it, run the tests.
```

## Sugar, not a second format

**A card and a task are two things.** A card is the file a person writes
(`CardSpec`); a task is what runs (`TaskSpec`); `expand()` is the only
crossing, so **nothing downstream of the loader knows cards exist**. The
expansion is visible (`poieo show`) and reversible (`poieo eject`) — the
moment it produces something you could not have written by hand, the short
form has become a hidden second configuration format.

```
CardSpec ──expand()──►  TaskSpec        name, graph, binding, trigger,
                                        enabled, isolation, carry_state: true
                    └►  GraphSpec       one `agent` node, id "work"
```

Defaults the card does not have to state: hourly (`every: 1h`), the binding's
default role, the `files` and `shell` toolsets, 40 turns, and `carry_state:
true` — a card is a standing job, so what it learned last night is in scope
tonight. Hand-written tasks still opt into carrying state.

`every: loop`, `every: 30m` and `at: "0 3 * * *"` are the schedule sugar;
`_trigger()` maps them onto the three real trigger types.

`role`, `tools`, `max_turns`, `deadline` and `prompt` describe the generated
node, so a card that names a `graph:` of its own may not also set them — there
would be nowhere to put them. `isolation:` is not a node key: it describes the
task, so `poieo eject` keeps it.

## Identity is the filename

`task.slug` is `source_path.stem`, never the `name:` field. The title on the card
can be rewritten without orphaning its run history, its journal, or the notes
other cards send it. Paths written inside a card resolve against the card file
itself (`task.resolve()`), so a card is self-contained whether the daemon loads
it or the CLI does.

`load_tasks(folder)` reads a whole folder. Graphs live there too — `eject` writes
one beside the card it came from — so the *document* says which is which: a card
has `folder:` and no `nodes:`, a graph the other way round. A file answering to
neither shape (or to both) is an error, deliberately: sorting them by trying to
parse each as a card and taking silence for a no would turn a typo into a task
that quietly stops running.

## The generated system prompt

`system_block()` is fixed in code because it is user-visible — `poieo show` prints
it. It states where the work happens, then splices in three things:

1. the project's memory, **only if the project keeps one** (see below)
2. `{{ input.journal }}` — supplied as run input, not baked in, because it is
   re-read before every run: a note written at 8am is in effect at 9am
3. the roster of cards this one may leave a note for, **only if** it took the
   `notes` toolset and there is anyone else

Each gate is on content, not configuration. A project that never made a memory
sees no trace of the feature — not even an empty header — and a card without
`notes` is not even told the other cards exist.

The prompt closes by asking for one line saying what was done, or that there was
nothing worth doing. That line is what `closing_line()` picks up.

## The journal

One markdown file per card at `memory/shortterm/<slug>.md`, appended to and never
rewritten.

```
- 2026-08-22 03:14 · did     fixed the flaky interval test on Windows
- 2026-08-22 08:02 · you     leave prose alone, spend the night on tests
- 2026-08-23 03:00 · task    [build-docs] rebuilt the docs; 30 links changed
```

It sits under `memory/` rather than beside the card, so the folder of
definitions does not go dirty in git on every run.

Four `kind`s write to it: `did` and `failed` (the card's own run), `you` (the
user, via `poieo note` or an editor), and `task` (a sibling's note). The tail is
read as text and never parsed, which is exactly what makes a hand-written line
work like one poieo wrote.

### Reading: the bookmark

`read_journal()` returns two parts, cut at the card's **own last completed
entry**:

```
New since you last worked:      everything after the bookmark, oldest first
What you did before that:       the tail of what came before, bounded
```

The split is by *position*, not by quantity, so no volume of notes can push
another out before it has been seen once. Only the half allowed to age out is
bounded (`JOURNAL_LIMIT = 20`). Oldest-first in the new half matters: showing the
newest would strand the oldest forever, since the bookmark only moves as far as
what was shown.

`_is_own_entry()` reads the kind by *structure* — a fixed field after the
separator — so a note whose text happens to mention "did" cannot forge a
bookmark and silently mark real notes as read. A **failed** run is deliberately
not a bookmark: it saw what had arrived but cannot be said to have handled it,
and repeating a note is recoverable where losing one is not.

### Writing: the contract

`record_run(task, result)` is the other half, and **every runner of a card must
land there** — the daemon's `TaskRunner._remember()` and `poieo run`'s one-shot
both do. A run that never writes a line leaves every note marked new forever and
its own work forgotten.

It writes two things: the full run record (see [memory.md](memory.md)) and one
journal line — the model's closing sentence on success, or the failure's
`cause` in the user's words on failure (`"the model could not be reached -- is
the server running? ..."`), since the journal is read by a model and a person
next run, and a sentence with an action beats an exception repr. The repr stays
in the run record for whoever wants it. Both writes swallow their own failures:
memory is not worth killing a night's work over.

## `card_payload()`

The one statement of what a card's generated graph gets beyond the user's input:
`journal`, and `memory` when the project keeps one. There are two runners —
`poieo run` by hand and the daemon at 3am — and they have to agree; a rule
written twice is a rule that eventually doesn't.

## Notes between cards

Opt in with `tools: [files, shell, notes]`. The card then has a `tell` tool and
its prompt lists who it may use it on. See [tools.md](tools.md) for the
mechanism; the design rule is that a note is news rather than an instruction, and
that it wakes nobody — it is read on the recipient's next scheduled run, so two
cards writing to each other still run only on their own triggers.
