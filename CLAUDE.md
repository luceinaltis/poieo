# poieo — working agreements

Rules for anyone, human or agent, changing this repository. Read this before your first
commit in a session.

## The shape of the repo

- `src/poieo/` — the package. `tests/` mirrors it.
- `docs/superpowers/specs/` — design specs, written before any code.
- `docs/superpowers/plans/` — task-by-task implementation plans derived from a spec.
- `.claude/worktrees/` — throwaway session worktrees, gitignored.

The remote is **public** (`github.com/luceinaltis/poieo`). Never commit an API key, a
token, or a real model transcript. Run logs (`.poieo/`, `examples/.poieo/`) are
gitignored — keep it that way.

## Branches

Work happens on a branch. `main` is the only long-lived one.

- Name a branch after its topic, no prefix: `agent-node`, `observation-backend`,
  `web-frontend`. When the work executes a plan, reuse the plan's slug —
  `docs/superpowers/plans/2026-08-22-web-frontend.md` → `web-frontend`.
- Small standalone fixes take a `fix-` prefix: `fix-windows-codepage`.
- **Branches named `worktree-*` are harness scratch.** The session worktree tool creates
  them with a random suffix. Never push one and never open a PR from one. If you are
  sitting on such a branch with real work to land, cut a properly named branch first:

  ```bash
  git switch -c web-frontend
  ```

- Branch off current `main`, not off another feature branch — unless the work genuinely
  depends on unmerged work, in which case say so in the PR body.
- Several worktrees are usually checked out at once and **the stash stack is shared
  between them**. Never run a bare `git stash` / `git stash pop`; you may pop another
  session's work. Set changes aside with a WIP commit instead.

## What needs a PR

**Anything touching `src/` or `tests/` goes through a PR.** That is the code, and the
code is what breaks.

Commit straight to `main` only for: typo and wording fixes in Markdown, ticking a
checkbox in a plan, and adding a spec or plan document that no code depends on yet
(`e2742d6`, `eae4df5`, `1a65cc3` all landed this way, correctly).

When you cannot tell which side of the line a change falls on, open the PR. An
unnecessary PR costs a minute; a broken `main` costs the next agent an hour.

## How big a PR should be

`main` uses **squash merge**, so a PR lands as exactly one commit. Size it so that one
commit is something you would want to find in `git log` and could revert on its own.

- Executing a plan: **one PR per Task.** The plans are already cut this way — Task 1 of
  the web frontend plan is a scaffold, Task 3 is a reducer. Those belong in `main` as
  separate commits, not as one seven-task blob. Group two tasks only when both are small
  and neither stands alone.
- Commit freely *inside* the branch. Those commits exist for review and squash discards
  them; the PR title and body are what survive.

## Commit and PR messages

Commits follow Conventional Commits, as the history does:

```
feat: agent nodes emit a node_turn event per model turn
fix: don't crash CLI output on legacy Windows console codepages
docs: observation API in README; mock demo shows thinking
refactor: extract call_with_retry and shape_output for reuse
chore: ignore .claude/worktrees
```

Design and plan documents are the one exception — they read as plain sentences
(`Add web observation design spec`).

The **PR title becomes the squashed commit subject**, so write it as one: Conventional
Commits, imperative, no PR number, no "WIP".

An agent ends every commit it authors with a trailer naming the model that wrote it:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

The PR body says what changed and why, and **pastes the actual verification output** —
the pytest summary line, the vitest run, the curl response. Not "tests pass". The output.

## Before you merge

Agents may merge their own PRs. **Nothing on GitHub enforces any of this** — `main` is
unprotected by choice, so the discipline below is the only thing standing between a bad
change and the next agent's afternoon. Run the gate; do not assume it.

```bash
# Python — the global pytest plugin on this machine is broken, hence the flags
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio

# Frontend, once web-ui/ exists — run mode, never watch (watch mode hangs an agent)
npm test --workspace web-ui
```

**Review your own diff before merging.** There is one GitHub account here and no second
reviewer, so self-review *is* the review — expected, not a shortcut. Read the whole change
as though someone else wrote it:

```bash
git diff main...HEAD
```

Look for what a green suite cannot tell you: a dropped error path, a public surface that
quietly widened, a comment that no longer matches the code below it, a file staged by
accident. Then write in the PR what you checked and what you found. "Self-reviewed, no
findings" under a 400-line diff is not a review.

Merge only when all of these hold:

1. Both suites are green, and the run appears in the PR body.
2. You have read the full diff and recorded that review in the PR.
3. The branch is current with `main` and conflict-free.
4. Every behaviour change has a test that fails without it. This repo is TDD — the plans
   are written test-first and the history follows it.
5. Nothing in the diff is an artifact you did not mean to check in.
   `src/poieo/web/static/` **is** deliberately checked in; `node_modules/` is not.

Then:

```bash
gh pr merge --squash --delete-branch
```

Stop and ask a human instead of merging when the PR changes a public interface, deletes a
test, adds a dependency no plan calls for, or touches how bindings and credentials are
loaded.

## Never

- Force-push `main`, or rewrite any commit already on `origin/main`.
- Push a `worktree-*` branch.
- Push code straight to `main` because opening a PR felt like overhead. Nothing will stop
  you. That is exactly why it is written down.
- Merge on a red or unrun suite, or reach for a skip marker to turn one green.
- Commit a secret, a token, or a real API transcript to this public repo.
