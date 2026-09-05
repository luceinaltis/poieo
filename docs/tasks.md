# Tasks

`src/poieo/card.py`

A task card is the short form for recurring work. It puts one task in one YAML
or JSON file and expands to the same `TaskSpec` and `GraphSpec` used by the
daemon. Downstream runtime code does not know whether a graph was authored
directly or generated from a card.

For the user workflow, start with [usage.md](usage.md).

## Card shape

```yaml
name: keep this project healthy
folder: ..
prompt: |
  Find one worthwhile maintenance change, make it, and run the tests.
every: 1h
enabled: true
```

A card requires `name` and exactly one of `prompt` or `graph`. A prompt card
also requires `folder`, because its generated agent has tools and needs a place
to work. Its optional fields are:

- schedule: exactly one of `every`, `at`, or a full `trigger` mapping;
- execution: `role`, `tools`, `max_turns`, `deadline`, `binding`, `isolation`;
- data: `input`, `input_file`;
- flow after completion: `then`, `on_error`;
- state: `enabled`.

Unknown keys are rejected. A graph-backed card cannot also declare
node-specific `prompt`, `role`, `tools`, `max_turns`, or `deadline`; those belong
in the graph once it has more than one authored step.

The filename stem is the stable task id. `name` is a title and may change
without changing stored history, journal paths, or API identity. Paths in a
card are relative to the card file after `~` expansion.

## Expansion

A prompt card expands to one `agent` node named `work`, with its prompt, role,
turn and deadline limits, and a text output alias named `summary`. Omitted
`tools` means the default `files` and `shell` toolsets; an explicit empty list
means no tools. The generated task carries state between runs. With no schedule
field, the card uses its interval default and runs once when residency starts.

`poieo show` displays the expanded form and `poieo eject` writes an explicit
graph. Expansion must remain reversible: it may add generated context, but it
must not create behavior that cannot be expressed by a normal task and graph.

The task-folder loader treats every YAML or JSON document without `nodes` as a
card. That makes a misspelled card field a validation error instead of a task
that silently disappears. A document mixing graph and card markers is rejected
as ambiguous -- whether it was found in the folder or named on the command line,
since one rule cannot give two answers.

## Run input and journal

Each run starts with the card's `input`; a mapping from `input_file` is reread
and layered over it. The harness then adds the task journal and, when enabled,
the project memory. A note or external input written after one run is therefore
visible to the next.

The journal is append-only at `memory/shortterm/<task>.md`. Every CLI and daemon
run records its outcome. Prompt assembly shows new notes in oldest-first order
before bounded older history, using the task's last successful own entry as the
bookmark. A failed run does not advance that bookmark, because repeating a note
is safer than losing it. Answering a question updates the run's recorded outcome
rather than leaving a permanent `asking` record.

When the card includes the `notes` toolset, its system context lists the other
task ids in the same project. `tell` may append to those journals only; it cannot
forge the sender, wake the recipient, or send outside the fixed roster. See
[tools.md](tools.md).

## Failure and extension

Card loading checks the folder, schedule shape, graph/binding paths, and
generated task before execution. Journal, result-memory, or long-memory read
failures warn and let the primary run continue with less context.

Add a card field only when it has one unambiguous expansion into an existing
task or graph contract. Multi-step logical behavior belongs in a graph, model
selection in a binding, and residency behavior in the daemon; duplicating any
of them in the short form would create a second configuration language.
