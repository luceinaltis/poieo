# poieo — working agreements

Rules for anyone, human or agent, changing this repository. Read this before your
first commit in a session.

**Nothing on GitHub enforces any of it.** `main` is unprotected by choice: no
required review, no CI gate, one account and no second reviewer. Everything below
is what stands in that place instead. That is why it is written down.

Two halves, and they rot at different speeds:

- **Part 1** is judgement. It changes when the way we work changes.
- **Part 2** is facts about this machine and this checkout. It goes stale on its
  own, and when it does the document is wrong and you should fix it.

---

# Part 1 · The agreements

## What needs a PR

**Anything touching `src/` or `tests/` goes through a PR.** That is the code, and
the code is what breaks.

Commit straight to `main` only for typo and wording fixes in Markdown, and a
documentation change that no code depends on yet.

When you cannot tell which side of the line a change falls on, open the PR. An
unnecessary PR costs a minute; a broken `main` costs the next agent an hour.

## How big a PR should be

`main` uses **squash merge**, so a PR lands as exactly one commit. Size it so that
one commit is something you would want to find in `git log` and could revert on
its own.

- Building a feature in slices: **one PR per slice.** A scaffold, then a reducer,
  then the screen that uses it belong in `main` as separate commits, not as one
  seven-part blob. Group two slices only when both are small and neither stands
  alone.
- Commit freely *inside* the branch. Those commits exist for review and squash
  discards them; the PR title and body are what survive.

## Before you merge

Agents may merge their own PRs. Run the gate — the exact three commands are in
Part 2 — and do not assume it.

**Review your own diff before merging.** With no second reviewer, self-review
*is* the review: expected, not a shortcut. Read the whole change as though
someone else wrote it:

```bash
git diff main...HEAD
```

Look for what a green suite cannot tell you: a dropped error path, a public
surface that quietly widened, a comment that no longer matches the code below it,
a file staged by accident. Then write in the PR what you checked and what you
found. "Self-reviewed, no findings" under a 400-line diff is not a review.

Merge only when all of these hold:

1. Both suites are green, and the run appears in the PR body.
2. You have read the full diff and recorded that review in the PR.
3. The branch is current with `main` and conflict-free.
4. Every behaviour change has a test that fails without it. This repo is TDD —
   write the test first, and the history follows it.
5. The component document in `docs/` still describes the code. A change that makes
   one of them wrong is not finished.
6. Nothing in the diff is an artifact you did not mean to check in.
   `src/poieo/web/static/` **is** deliberately checked in; `node_modules/` is not.
7. `git status` is clean after the suite has run. Twice, a test's own output rode
   into a commit because it wrote to a tracked file and `git add -A` swept it up.
   A session fixture now fails the run if the suite writes into `examples/`.
8. **A diff that touches `web-ui/src/` rebuilds the bundle in the same PR:**
   `npm run build --workspace web-ui`, then commit `src/poieo/web/static/`.
   Neither suite reads that folder, so it drifts in silence. It sat four PRs
   behind `main` before anyone opened the daemon and looked, and one of those
   four was a CSS fix -- so a fresh checkout served the bug that `main` had
   already fixed, with both suites green over it the whole time.

Stop and ask a human instead of merging when the PR changes a public interface,
deletes a test, adds a dependency nothing asked for, or touches how bindings and
credentials are loaded.

## Commit and PR messages

Commits follow Conventional Commits, as the history does:

```
feat: agent nodes emit a node_turn event per model turn
fix: don't crash CLI output on legacy Windows console codepages
docs: observation API in README; mock demo shows thinking
refactor: extract call_with_retry and shape_output for reuse
chore: ignore .claude/worktrees
```

Documentation-only changes take `docs:`, and may read as a plain sentence after it
(`docs: the layout gets a name, a scaffold, and a manual that is true`).

The **PR title becomes the squashed commit subject**, so write it as one:
Conventional Commits, imperative, no PR number, no "WIP".

An agent ends every commit it authors with a trailer naming the model that wrote
it:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

The PR body says what changed and why, and **pastes the actual verification
output** — the pytest summary line, the vitest run, the curl response. Not "tests
pass". The output.

## The shape of the repo

- `src/poieo/` — the package. `tests/` mirrors it.
- `docs/` — **one document per component**, describing how it works today.
  `docs/README.md` is the index. When you change a component's shape, edit its
  document in the same PR; the docs are the map the next agent reads.
- `docs/archive/` — the dated design specs and implementation plans features were
  built from. History: read it for intent, never for current behaviour, and do not
  add to it.

Do not start a new dated file. A design worth writing down belongs in the
component document it describes, and git already records when and why it changed.

The remote is **public** (`github.com/luceinaltis/poieo`). Never commit an API key,
a token, or a real model transcript. A project's run logs live in `runs/`, which is
gitignored — keep it that way.

## Never

- Force-push `main`, or rewrite any commit already on `origin/main`.
- Push a `worktree-*` branch.
- Push code straight to `main` because opening a PR felt like overhead. Nothing
  will stop you. That is exactly why it is written down.
- Merge on a red or unrun suite, or reach for a skip marker to turn one green.
- Commit a secret, a token, or a real API transcript to this public repo.

---

# Part 2 · This machine

Facts about this checkout, not principles. They go stale on their own: a path gets
renamed, a tool gets fixed, a quirk goes away. **If one of these is wrong, the
document is wrong — fix it in the PR where you found out.**

## The gate, exactly

```bash
# Python — the global pytest plugin on this machine is broken, hence the flags
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio

# Frontend — run mode, never watch (watch mode hangs an agent)
npm test --workspace web-ui

# ...and the types, which vitest does not check. A fixture that no longer matches
# an interface in web-ui/src/types.ts passes `npm test` and fails only here.
cd web-ui && npx tsc -b
```

## Branches and worktrees

Work happens on a branch. `main` is the only long-lived one.

- Name a branch after its topic, no prefix: `agent-node`, `observation-backend`,
  `web-frontend`. Small standalone fixes take a `fix-` prefix:
  `fix-windows-codepage`.
- Branch off current `main`.
- **Branches named `worktree-*` are harness scratch.** The session worktree tool
  creates them with a random suffix. Never push one and never open a PR from one.
  If you are sitting on such a branch with real work to land, cut a properly named
  branch first: `git switch -c web-frontend`.
- Several worktrees are usually checked out at once and **the stash stack is
  shared between them**. Never run a bare `git stash` / `git stash pop`; you may
  pop another session's work. Set changes aside with a WIP commit instead.

## When `main` moves under you

It will, more than once in a working session. Condition 3 is not a formality:

```bash
git fetch origin && git rebase origin/main
```

Then **run the whole gate again**. A rebase that applied cleanly past a rename
refactor proves the syntax still fits, not that the meaning does — the names it
replayed your code onto may mean something else now. If the change has a way to be
exercised by hand, exercise it.

## Stacking on unmerged work

Branch off another branch only when the work genuinely depends on it, and say so
in the PR body along with the base.

Squash merge rewrites history, so when the parent lands, its commit on `main` is a
**new** object and rebasing onto `main` normally would replay the parent's changes
a second time. Move the child from the parent's *pre-merge* tip:

```bash
git rebase --onto origin/main $PARENT_TIP $BRANCH   # $PARENT_TIP: the parent's
git push --force-with-lease origin $BRANCH          # last commit before merging
```

`$PARENT_TIP` is the commit the parent branch pointed at while its PR was open —
still in `git reflog` if the local branch is gone. Getting it wrong replays the
parent's commits into your diff; `git log origin/main..HEAD` should show only
your own, and if it does not, `git rebase --abort` and pick the tip again.

Then re-run the gate, as above.

## Things that break here

`gh pr merge --squash --delete-branch` **fails after the merge has already gone
through**: it tries to switch this checkout to `main`, which is checked out in the
primary worktree, so git refuses. The PR really is merged and the remote branch is
already gone. Confirm, then delete the local branch by hand:

```bash
gh pr view <n> --json state --jq .state    # expect MERGED
git switch --detach origin/main && git branch -D <branch>
```
