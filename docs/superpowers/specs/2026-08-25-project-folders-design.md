# Project Folders Design

**Date:** 2026-08-25
**Status:** Approved for planning
**Relates to:** `2026-08-22-user-experience-gaps.md` (the onboarding cost it never named),
DESIGN.md principle 2 (minimal configuration) and principle 4 (everything is a file)

## Goal

A folder becomes a poieo project the way a folder becomes a git repository:
one marker file at its root, and every command typed anywhere inside it knows
where it is. The user stops carrying context in flags that the project already
wrote down.

Today the knowledge lives in the right file — `poieo.yaml` names the store,
the default binding, and the tasks folder — but only `poieo daemon` ever reads
it. `poieo run` demands `-b` for anything that is not a card naming its own
binding, `poieo check` demands `-b` always, and `poieo runs list` without
`--store` does not even fail in the product's voice: it prints a raw
`TypeError` traceback, while its own help text advertises a default that was
never implemented.

The end state, from an empty folder:

```
poieo init          # writes the project: poieo.yaml, bindings/, tasks/
poieo run tasks/hello.yaml    # no -b: the project's default binding answers
poieo runs list               # no --store: the project's store answers
poieo daemon                  # no argument: the project's config answers
```

## The project file

`poieo.yaml` — the existing daemon config, unchanged — is the marker. A
project is the folder that holds one. No new file format, no new keys: the
three keys a project needs (`store`, `binding`, `tasks`) have been there since
the daemon shipped.

**Discovery** walks from the current directory upward to the filesystem root
and stops at the first `poieo.yaml`. Only that literal filename marks a
project; a config passed explicitly by path may be called anything, exactly as
today. Commands that take an explicit path or flag never consult discovery —
**the flag always wins, and discovery only fills silence.**

## What each command gains

Resolution chains, first match wins. Every chain ends where the command ends
today, so a folder with no `poieo.yaml` behaves exactly as before.

**Binding** — `run`, `validate`, `learn`, and `check` (whose `-b` becomes
optional, aligning it with every other command):

1. the `-b` flag
2. the card's own `binding:` (as today)
3. the project's `binding:`
4. fail — the message now also names `poieo init` as the way to get a default

**Store** — `runs list` and `runs show`:

1. the `--store` flag
2. the project's `store:`
3. `./.poieo` (what the help text has promised all along)

`poieo run` keeps its beside-the-card rule but consults the project first:
flag, then the project's `store:`, then beside the card, then `./.poieo`.
Without this, a run typed by hand and the same card run by the daemon would
write two divergent histories — the daemon into the project store, the hand
run into a `.poieo` beside the card.

**Config** — `poieo daemon` and `poieo flows` with no argument use the
discovered `poieo.yaml`; with no project, they fail naming `poieo init`.

**Transparency.** A filled-in default must not be a silent one. When discovery
supplies the binding, `run` and `validate` say so in one line
(`binding    bindings/mock.yaml  (from poieo.yaml)`); when it supplies the
store and there is nothing to list, the empty message names the store it
searched. Automatic is fine, invisible is not.

## `poieo init`

One command, zero questions. It looks at the machine once, writes what it
found into ordinary files, and from then on only the files matter — detection
never happens again at run time, so no night's run can silently pick a
different model than the one written down (principle 4, and the billing
surprise it prevents).

Detection order for the default binding:

1. `ANTHROPIC_API_KEY` is set → a `claude` binding
2. Ollama answers on `localhost:11434` (one probe, one-second timeout) and
   has at least one model installed → an `ollama` binding naming the first
3. neither → the `mock` binding is the default

What it writes:

```
poieo.yaml               store: .poieo · binding: bindings/default.yaml · tasks: tasks/
bindings/default.yaml    what detection found
bindings/mock.yaml       always — the no-token try-it path stays one flag away
tasks/hello.yaml         a commented sample card, enabled: false
.gitignore               gains a `.poieo/` line (created if absent)
```

The sample card ships disabled so that pointing the daemon at the project
never spends a token on a demo; `poieo run tasks/hello.yaml` still runs it by
hand. Every file is created only if absent — `init` in an existing project
overwrites nothing, reports `wrote` or `kept` per file, and is safe to run
twice. The last lines of output are the next two commands to type.

## Out of scope

- **Binding composition** (`extends`, fallback chains, role aliases) — its own
  spec, later. This design only decides *which file* answers, not what a
  binding file may contain.
- **`poieo run` with no argument.** A project holds many cards and guessing is
  worse than listing; `poieo tasks tasks/` already lists.
- **Multi-project nesting rules.** Nearest file wins, full stop.
- The web surface. The API serves whatever project the daemon was started in,
  as today.

## Compatibility

Every existing invocation keeps its exact behaviour: all current flags remain,
explicit paths are never second-guessed, and discovery adds defaults only
where the command previously failed (or crashed). The one visible change in a
flagless world is intended: commands succeed where they used to demand flags.
