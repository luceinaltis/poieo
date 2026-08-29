# Contributing: the longer procedures

`AGENTS.md` holds the rules, and every session loads it whole, so it is kept
short. This document holds the procedures those rules send you to — steps that
matter only sometimes, worth reading when you are in the situation and worth
nothing before. A rule belongs there; the incantation belongs here.

Each section names the rule that sends you here, so neither drifts alone.

## The checked-in bundle

*Merge condition 8.* You changed something under `web-ui/src/`. **The built
bundle is checked in, and rebuilding it is part of the same PR:**

```bash
npm run build --workspace web-ui
```

Then commit `src/poieo/web/static/`. That folder is deliberately tracked — it is
what a fresh checkout serves — while `web-ui/dist/` and `node_modules/` are
ignored.

Neither suite reads `src/poieo/web/static/`, so it drifts in silence. It once sat
four PRs behind `main`, and one of those four was a CSS fix, so a fresh checkout
served the bug `main` had already fixed — with both suites green over it the
whole time. **A green run is not evidence that the bundle is current; only the
rebuild is.**

## Stacking on unmerged work

*Part 2, "Stacking on unmerged work".* Branch off another branch only when the
work genuinely depends on it, and say so in the PR body along with the base.

### Why the ordinary rebase is wrong here

`main` uses squash merge, so when the parent's PR lands, its commit on `main` is
a **new** object with a new hash. The child branch still carries the parent's
original commits. Rebasing the child onto `main` the usual way replays those a
second time, and the child's diff silently grows to include work already merged.

### Move the child from the parent's pre-merge tip

```bash
git rebase --onto origin/main $PARENT_TIP $BRANCH
git push --force-with-lease origin $BRANCH
```

`$PARENT_TIP` is the commit the parent branch pointed at **while its PR was
open** — its last commit before merging. If the local branch is already deleted,
find it in `git reflog`.

### Check before you trust it

```bash
git log origin/main..HEAD
```

This should list only commits you wrote. If the parent's commits appear, the tip
was wrong: `git rebase --abort` and pick it again.

Then re-run the full gate from `AGENTS.md` Part 2. A rebase that applied cleanly
past a rename refactor proves the syntax still fits, not that the meaning does.
