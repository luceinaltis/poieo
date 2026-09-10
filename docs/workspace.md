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

`accept(through)` refuses tracked local changes and changes that no longer
belong to the task. It prepares the combined result in a disposable private
copy, then fast-forwards the user's branch to that exact result. A divergent
history receives an acceptance commit in the private copy; even a conflicting
merge never touches the user's checkout. `through` accepts only up to a
selected run.

`prepare_accept()` exposes that private result for verification before
`apply_prepared()` applies it. The latter rechecks the user's branch identity,
commit and local edits, the task's ownership of the change, and the candidate's
commit and tracked files. If any changed, the result must be prepared and
checked again. A same-file overlap may merge cleanly; only checking the combined
result can establish whether its behavior still works.

Applying and discarding use a lock in the repository's common Git directory,
shared across tasks and poieo processes. Preparing or verifying a result does
not reserve the project until application; a competing application makes the
older candidate stale. This lock coordinates poieo, not edits made by another
program. Git also refuses to overwrite conflicting local edits.

A separate per-task file lock spans each complete run and each manual decision.
This prevents a CLI run or another daemon from resetting an in-progress task
copy. Other tasks keep working independently. A busy task is refused immediately.

`release_prepared()` removes only its owned temporary copy. The task branch and
all recorded run references survive, including a candidate refused for conflict.

`discard(since)` first parks the old task tip under a recoverable ref, then
resets the task branch to before the selected run or to the user's `HEAD`.
Discarding removes work from the review queue but does not make its commit
unreachable.

## Failure and extension

`ApplySpec` validates the user's application settings. `working_folder()` and
`check_folder()` preserve a task folder below the repository root in both private
copies. `outside_scope()` inspects the combined file delta with rename detection
disabled, so a permitted destination cannot hide an unauthorized source deletion.
`validate_prepared()` rejects verification that changed tracked files or HEAD.
Before repair, generated untracked and ignored files are removed only from the
owned temporary review copy; check output cannot become part of the saved repair.
`save_repair()` commits a resolved combination, keeps its run reference, and
fast-forwards the task's private branch so both a failed check and a stale
project retain the repair for the next attempt. It rejects unresolved conflict
markers or a repair that rewrote candidate history. The original project still
moves only through `apply_prepared()` after verification.

`prepare_undo()` reverses the net file delta of a recorded application using a
synthetic single-parent commit. Git's three-way revert preserves later edits
when compatible. The candidate is verified and applied through the ordinary
checked path. An undo marker is prepared before application and only counts as
done when its commit belongs to the project's history, covering a crash between
the file update and run-record update.

In review mode, when Git is unavailable or the folder is not in a work tree, the daemon warns
and runs directly in the folder. The run still completes, but there is no
change to accept or discard. Anything Git cannot prove is treated as
unreviewable. A half-registered worktree is disposable and may be pruned and
recreated; task branches and run refs are not.

Automatic mode requires Git at startup. Any later failure to prepare a private
copy stops that task before its tools run. Nodes with their own working folders
are refused in automatic mode; the task's chosen folder is the application scope.

Workspace methods are synchronous. Daemon and web callers run them away from
the shared event loop. Git behavior belongs in this module; other components
consume `Change` data and refusal results rather than invoking Git themselves.
