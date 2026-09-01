# Workspace

`src/poieo/workspace.py`

A task working inside a Git repository uses a linked worktree on its own branch.
The user's checkout is untouched while runs are in progress, and each run's
files become one reviewable change. This is an undo boundary, not a process
sandbox; [tools.md](tools.md) describes command isolation.

## Persistent objects

| object | location |
|---|---|
| task branch | `poieo/<task>` |
| linked worktree | `<project>/worktrees/<task>` |
| each run tip | `refs/poieo/runs/<run-id>` |
| failed run tip | `refs/poieo/failed/<run-id>` |
| discarded tip | `refs/poieo/discarded/<run-id>` |

The branch persists across runs so several pending changes can be reviewed in
order. Before a run, `prepare()` creates or repairs the linked worktree. It
follows the user's current `HEAD` only when no task commits are pending; unread
work is never rebased away automatically.

After a run, `commit()` stages tracked and untracked work. No changes returns no
`Change`. Otherwise it creates one commit with poieo's local Git identity,
records the run ref, and returns base/head ids, file names, counts, and the run's
closing message. A failed run is also parked under its failed ref and the task
branch is reset, so partial work does not mix with acceptable work.

## Review operations

`diff(base, head)` returns per-file status and counts plus a bounded patch;
binary files remain listed and an oversized patch is marked truncated.

`accept(through)` is the only write to the user's checked-out branch. It refuses
tracked local changes. It fast-forwards when possible, otherwise performs a
no-commit merge and creates one acceptance commit. A conflict is aborted and
returned as a path list with the checkout restored. `through` allows accepting
only up to a selected run.

`discard(since)` first parks the old task tip under a recoverable ref, then
resets the task branch to before the selected run or to the user's `HEAD`.
Discarding removes work from the review queue but does not make its commit
unreachable.

## Failure and extension

When Git is unavailable or the folder is not in a work tree, the daemon warns
and runs directly in the folder. The run still completes, but there is no
change to accept or discard. Anything Git cannot prove is treated as
unreviewable. A half-registered worktree is disposable and may be pruned and
recreated; task branches and run refs are not.

Workspace methods are synchronous. Daemon and web callers run them away from
the shared event loop. Git behavior belongs in this module; other components
consume `Change` data and refusal results rather than invoking Git themselves.
