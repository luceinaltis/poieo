# Workspace — the private copy, and the morning after

`src/poieo/workspace.py` — the only module in poieo that knows git exists.

A task that names a `workdir` works in a private copy — a linked git worktree
on a branch of its own — never in the user's checkout. Each run lands as one
change to read, take, or throw away. Autonomy without undo is a different,
scarier product.

## What exists per task

| thing | where |
|---|---|
| the branch | `poieo/<task>` in the user's own repository |
| the working copy | `<project>/worktrees/<task>` |
| every run's tip | `refs/poieo/runs/<run_id>` |
| a failed run's work | `refs/poieo/failed/<run_id>` |
| a discarded tip | `refs/poieo/discarded/<run_id>` |

The worktrees folder belongs to the *project*, not the run-log store — a copy
of a repository is not a log (see [storage.md](storage.md)). Every run stays
reachable by its own ref; nothing here ever deletes work.

## The run boundary

`prepare()` — before the run:

1. read the user's `HEAD`
2. create `poieo/<task>` at it if missing, and materialise the worktree
3. **if nothing is pending review**, hard-reset the copy to the user's `HEAD`
   — follow the user forward only while there is nothing to lose

`commit(run_id, message, failed=)` — after the run:

1. `add -A`; an empty index returns `None` — a run that found nothing to do
   leaves nothing to review
2. commit, and point `refs/poieo/runs/<run_id>` at the tip
3. a failed run is also parked at `refs/poieo/failed/<run_id>` and the branch
   reset back, so half-finished work never mixes with acceptable work
4. return a `Change`: `base`, `head`, files, insertion/deletion tally, message

The message is the model's closing sentence (first line, 72 chars) via the
same `closing_line()` the journal and run record use, so the three accounts of
a run cannot disagree.

## The morning after

`accept(through=None)` — **the one write poieo ever makes to the user's own
branch**:

- refuses if the checkout has *tracked* changes → `{"dirty": [...]}`.
  Untracked files are ignored (the store often lives inside the project).
- fast-forwards when possible; otherwise `--no-commit --no-ff` merge. On
  conflict: abort, return `{"conflict": [...]}`, checkout left as found.
- `through` accepts up to one run's commit instead of the whole branch.

`discard(since=None)` parks the old tip at `refs/poieo/discarded/<run_id>`
before resetting — recoverable, always.

`diff(base, head)` feeds the review screen: per-file status and counts from
`--name-status` / `--numstat` plus the patch, truncated at 400 kB with a
`truncated` flag. A rename's **last** field is the path to report; binary
files list with zeroed counts rather than being skipped.

## Rules the module holds

- **Synchronous throughout; every caller wraps it in `asyncio.to_thread`** —
  the daemon shares one event loop with the web server, and a blocking
  subprocess there would stall every watcher.
- **A `WorkspaceError` is never fatal to a task.** The run happens in the
  folder directly, with a warning that its changes cannot be reviewed or
  undone.
- `usable(folder)` exposes that condition standalone (git on PATH, folder in a
  work tree) because the board asks it of a project that owns no task yet —
  see [web.md](web.md). Anything git cannot answer is False, the safe
  direction to be wrong in.
- **Commits carry poieo's own identity** (`-c user.name=poieo …`), so they
  work on a machine with no global git config.
- **The worktree directory is disposable** — a half-registered one is pruned
  and recreated.

## What it does not protect

The folder itself: that is the work, exposed by definition. Isolation
([tools.md](tools.md)) protects everything outside it; this protects the
user's checkout from the copy.
