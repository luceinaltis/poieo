---
name: stack-branch
description: Rebase a branch that was cut from another unmerged branch, after the parent's PR squash-merges into main. Use when a PR is stacked on another PR, when moving a child branch onto main would replay the parent's commits into your diff, or when `git log origin/main..HEAD` shows commits you did not write.
---

# Stacking on unmerged work

Branch off another branch only when the work genuinely depends on it, and say so in
the PR body along with the base.

## Why the ordinary rebase is wrong here

`main` uses squash merge, so when the parent's PR lands, its commit on `main` is a
**new** object with a new hash. The child branch still carries the parent's original
commits. Rebasing the child onto `main` the usual way replays those a second time,
and the child's diff silently grows to include work that is already merged.

## Move the child from the parent's pre-merge tip

```bash
git rebase --onto origin/main $PARENT_TIP $BRANCH
git push --force-with-lease origin $BRANCH
```

`$PARENT_TIP` is the commit the parent branch pointed at **while its PR was open** —
its last commit before merging. If the local branch is already deleted, find it in
`git reflog`.

## Check before you trust it

```bash
git log origin/main..HEAD
```

This should list only commits you wrote. If the parent's commits appear, the tip was
wrong: `git rebase --abort` and pick it again.

Then re-run the full gate from CLAUDE.md Part 2. A rebase that applied cleanly past a
rename refactor proves the syntax still fits, not that the meaning does.
