# poieo — working agreements

Rules for anyone, human or agent, changing this repository. Read this before your
first commit in a session.

**Nothing on GitHub blocks any of it.** `main` is unprotected by choice: no required
review, one account, no approval anything can insist on; CI reports on every PR but
cannot stop a merge. Everything below stands in that place, which is why it is written.

Two halves that rot at different speeds. **Part 1** is judgement. **Part 2** is
facts about this machine, and goes stale on its own — when it does, fix it.

---

# Part 1 · The agreements

## What needs a PR

**Anything touching `src/` or `tests/` goes through a PR.** That is the code, and
the code is what breaks. Commit straight to `main` only for typo and wording fixes
in Markdown, and documentation no code depends on yet.

When you cannot tell which side of the line a change falls on, open the PR. An
unnecessary PR costs a minute; a broken `main` costs the next agent an hour.

## How big a PR should be

`main` uses **squash merge**, so a PR lands as exactly one commit. Size it so that
one commit is something you would want to find in `git log` and could revert on its
own.

Building a feature in slices means **one PR per slice**: a scaffold, then a reducer,
then the screen that uses it land as separate commits, not one seven-part blob.
Group two slices only when both are small and neither stands alone. Commit freely
inside the branch; only the PR title and body survive the squash.

## Before you merge

Agents may merge their own PRs. Run the gate — the exact three commands are in
Part 2 — and do not assume it.

**Review your own diff before merging** (`git diff main...HEAD`), then have a reader
that did not write it go over the same diff; `docs/contribution.md` says what counts.
Self-review cannot see what you already believe. Look for what a green suite cannot:
a dropped error path, a surface that quietly widened, a stale comment, a file staged
by accident. "Self-reviewed, no findings" under a 400-line diff is not one.

And ask where each part came from. Most requirements here arrive from
`docs/archive/`, written by earlier sessions no longer available to be asked —
capable ones, which makes them more dangerous to trust, not less. **Before making a
part faster or more configurable, find out whether the reason it exists is still
true.** Delete hard enough that some of it has to come back.

Merge only when all of these hold:

1. Both suites are green in the checks, and you ran them here too — CI is Ubuntu
   only, and this is the Windows machine.
2. You read the whole diff, an independent pass read it too, and both are in the PR.
3. The branch is current with `main` and conflict-free.
4. Every behaviour change has a test that fails without it. This repo is TDD —
   write the test first, and the history follows it.
5. The component document in `docs/` still describes the code. A change that makes
   one of them wrong is not finished.
6. Nothing in the diff is an artifact you did not mean to check in.
   `src/poieo/web/static/` **is** deliberately checked in; `node_modules/` is not.
7. `git status` is clean after the suite ran. Twice a test's output rode into a commit
   via `git add -A`; a fixture now fails the run if the suite writes into `examples/`.
8. **A diff that touches `web-ui/src/` rebuilds the bundle in the same PR** — neither
   suite reads it, so it drifts in silence. `npm run build --workspace web-ui`, then
   commit `src/poieo/web/static/`. `docs/contribution.md` has the story.
9. The change fits the one set of ideas the product already has — a system that omits
   a good feature to keep one design beats one carrying many uncoordinated ones, and
   DESIGN.md judges that. A PR that works and runs green is still refused if it adds
   a fourth word beside task / run / change, or a second way to say an existing one.

Stop and ask a human instead of merging when the PR changes a public interface,
deletes a test, adds a dependency nothing asked for, or touches how bindings and
credentials are loaded.

That list is short on purpose, and every item is a **one-way door**: a revert undoes
a merge, but not an interface other code now calls, the only written record of a
behaviour, or a leaked credential. Everything else is two-way, and deciding those
slowly buys only delay. **Stopping to ask is for the one-way items, not the rest.**

## Commit and PR messages

Commits follow Conventional Commits, as `git log` shows: `feat:`, `fix:`,
`refactor:`, `chore:`. Documentation-only changes take `docs:` and may read as a
plain sentence after it.

The **PR title becomes the squashed commit subject**, so write it as one:
imperative, no PR number, no "WIP". An agent ends every commit it authors with a
trailer naming the model: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

The PR body says what changed and why, and **pastes what CI could not run for you** —
a curl response, a Windows-only run, anything exercised by hand — as output, not a claim.

## The shape of the repo

- `docs/` — **one document per component**, describing how it works today, plus two
  that are not components: `conventions.md`, how code here is written and where that
  departs from generic good taste, read before your first change to `src/`; and
  `contribution.md`, the longer procedures these rules send you to. `docs/README.md`
  is the index, and a component's document is edited in the PR that changes its shape.
- `docs/archive/` — dated design specs features were built from. History: read it
  for intent, never for current behaviour, and never add to it. Do not start a new
  dated file anywhere; a design belongs in the component document it describes.

The remote is **public** (`github.com/luceinaltis/poieo`). Never commit an API key, a
token, or a real model transcript. Run logs live in gitignored `runs/`; keep it there.

## How long this document is

Every session loads this file whole, so its length is paid on every turn — not in
tokens, which are cheap, but in attention: a rule buried under nineteen paragraphs
competes with all nineteen. **Keep it under 200 lines**, which is the documented
target, not a local invention. It grew from 127 lines to 257 in its first week and
nothing was ever cut, so a PR that adds here says what it cut.

What belongs: the rules, and the facts about this machine an agent cannot recover
from the code. What does not: anything git, `docs/`, or the source already says, and
the second example of a rule the first made clear. Reasons stay, as a sentence.

Overflow goes to `docs/`, which costs nothing until it is opened: a procedure that
matters only sometimes to `docs/contribution.md`, a fact about one component to that
component's document. An `@import` is not overflow — it expands at launch, buying
back nothing — which is why root `CLAUDE.md` holds exactly one line, `@AGENTS.md`,
so Claude Code loads the page every other agent reads by its own name.

## Never

- Force-push `main`, or rewrite any commit already on `origin/main`.
- Push code straight to `main` because opening a PR felt like overhead.
- Merge on a red or unrun suite, or reach for a skip marker to turn one green.
- Commit a secret, a token, or a real API transcript to this public repo.

---

# Part 2 · This machine

Facts about this checkout, not principles; they go stale on their own. **If one of
these is wrong, the document is wrong — fix it in the PR where you found out.**

## The gate, exactly

```bash
# Python — tests then lint; the flags dodge a broken global pytest plugin here
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio && ruff check .

# Frontend — run mode, never watch (watch mode hangs an agent)
npm test --workspace web-ui

# ...and the types, which vitest does not check. A fixture that no longer matches
# an interface in web-ui/src/types.ts passes `npm test` and fails only here.
cd web-ui && npx tsc -b
```

## Branches and worktrees

Work happens on a branch, cut from current `main`; `main` is the only long-lived
one. Name a branch after its topic, no prefix: `agent-node`, `observation-backend`,
`web-frontend`. Small standalone fixes take a `fix-` prefix: `fix-windows-codepage`.

- **Branches named `worktree-*` are harness scratch**, created by the session
  worktree tool with a random suffix. Never push one or open a PR from one; if you
  are on one with real work to land, name it first: `git switch -c web-frontend`.
- Several worktrees are usually checked out at once and **the stash stack is shared
  between them**. Never run a bare `git stash` / `git stash pop`; you may pop another
  session's work. Set changes aside with a WIP commit instead.

## When `main` moves under you

It will, more than once in a working session. Condition 3 is not a formality:

```bash
git fetch origin && git rebase origin/main
```

Then **run the whole gate again**. A rebase that applied cleanly past a rename
refactor proves the syntax still fits, not that the meaning does. If the change has
a way to be exercised by hand, exercise it.

## Stacking on unmerged work

Branch off another branch only when the work genuinely depends on it, and say so in
the PR body along with the base. Squash merge makes the rebase counter-intuitive —
moving the child onto `main` the usual way replays the parent's commits into your
diff. **`docs/contribution.md`** has the `--onto` incantation and the check for it.

## Things that break here

`gh pr merge --squash --delete-branch` can **fail after the merge has gone through**:
if another worktree holds `main` it tries to switch there and git refuses. It exits 0
when nothing does. The merge landed either way — trust the state, not the exit code:

```bash
gh pr view <n> --json state --jq .state    # expect MERGED
git switch --detach origin/main && git branch -D <branch>
```
