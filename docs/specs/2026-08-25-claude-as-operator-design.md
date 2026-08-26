# Claude as Operator Design

**Date:** 2026-08-25
**Status:** Approved for planning
**Relates to:** `2026-08-25-project-folders-design.md` (init), DESIGN.md principle 4
(everything is a file) and principle 7 (a small vocabulary)

## Goal

poieo has two kinds of user and they want opposite interfaces. The person wants
a browser: cards on a board, a diff, two buttons. A coding agent — Claude Code
or its kin, told "add a nightly task that keeps the tests green" — wants files
and a shell: it cannot click, but it edits YAML and reads exit codes better
than anyone.

The library already serves both; only the surfaces are unfinished. Three moves
close the gap, none of which adds a concept:

1. **`poieo init` teaches the agent.** The project gains an operating manual an
   agent reads before touching anything.
2. **`--json` everywhere an agent looks.** Structured output for the three
   commands that answer questions.
3. **The help shrinks to the two stories.** Six commands visible; the rest keep
   working, hidden.

## 1. init writes the agent's manual

Coding agents read a project's `AGENTS.md` (and Claude Code its `CLAUDE.md`)
before working. A poieo project should carry one from birth, so any agent
session opened in it immediately drives poieo correctly instead of guessing
from the README.

`poieo init` additionally writes, each only if absent, reported `wrote`/`kept`
like every other file:

- **`AGENTS.md`** — one page: this is a poieo project; a task is one YAML card
  in `tasks/` (name, folder, prompt); after editing any poieo file run
  `poieo validate <file>`; try a card once with `poieo run`; inspect with
  `poieo runs list` / `runs show`; never edit `.poieo/` (derived state);
  starting the daemon and reviewing work belong to the person.
- **`CLAUDE.md`** — a single `@AGENTS.md` import line, so Claude Code loads the
  same page. Never written when the user already has one.

The manual is generated content, not a template the user must maintain: short,
stable, and pointing at the README for everything else.

## 2. `--json` for the commands that answer questions

`run` and `runs show` already speak JSON. The remaining question-answering
commands gain the same flag:

- `validate --json` — the facts it already prints, structured: graph name,
  entry, roles, schedule when a card, the binding and per-role resolution when
  one is found. Failures are unchanged (stderr, exit 1): the exit code is the
  contract, and error text stays in the product's voice.
- `check --json` — `[{provider, healthy, detail}]`, exit code unchanged.
- `runs list --json` — the summary rows as a JSON array.

No output *format* changes for humans; the flag is additive.

## 3. Help tells two stories, not seventeen

`poieo --help` currently lists every command as an equal. The agreed surface:

- **Visible:** `init`, `daemon`, `run`, `validate`, `check`, `runs`.
- **Hidden, still working:** `show`, `view`, `edit`, `flows`, `tasks`, `note`,
  `memory`, `learn`, `eject`, `reset`, `version`. Each is either plumbing, a
  file the user can edit directly, or a view the web board now owns. Hiding is
  `hidden=True`, not deletion: no script breaks, and any of them can return to
  the help if the web board retreats.

Removal (as opposed to hiding) waits for the web control plane, which is the
only surface that can replace card CRUD for the person.

## Out of scope

- An MCP server. The CLI is already deterministic, prompt-free, and
  exit-code-honest — a fine agent interface. Revisit only if live observation
  of a running daemon becomes an agent need.
- Rewriting the README around the two stories — after all three land.
- Any change to what the commands do.
