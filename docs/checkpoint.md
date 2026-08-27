# Checkpoint — the private copy, and the morning after

`src/poieo/checkpoint.py`

**The only module in poieo that knows git exists.**

A flow that names a `workdir` does not work in the user's checkout. It works in a
private copy — a linked git worktree on a branch of its own — so a night of runs
never touches what the user left open, and each run lands as one change that can
be read, taken, or thrown away in the morning.

Autonomy without undo is a different, scarier product. This is what makes hands
safe to hand out.

## What exists per flow

| thing | where |
|---|---|
| the branch | `poieo/<flow>` in the user's own repository |
| the working copy | `<project>/worktrees/<flow>` |
| every run's tip | `refs/poieo/runs/<run_id>` |
| a failed run's work | `refs/poieo/failed/<run_id>` |
| a discarded tip | `refs/poieo/discarded/<run_id>` |

The worktrees folder is the *project's*, not the run-log store's. This used to be
handed the store and append `worktrees` itself, which meant pointing the logs at
another disk quietly took the working copies along — a copy of a repository is
not a log. See [storage.md](storage.md).

Every run stays reachable by its own id, accepted or not. Nothing here ever
deletes work.

## The run boundary

`prepare()` — before the run:

1. read the user's `HEAD`
2. create `poieo/<flow>` at it if it does not exist, and materialise the worktree
3. **if nothing is pending review**, hard-reset the copy to the user's `HEAD` —
   follow the user forward only while there is nothing to lose. Rebasing unread
   work out from under them would lose it.

`commit(run_id, message, failed=)` — after the run:

1. `add -A`; **if the index is empty, return `None`** — a run that found nothing
   to do is not a failure and leaves nothing to review
2. commit, and point `refs/poieo/runs/<run_id>` at the new tip
3. if the run failed, also point `refs/poieo/failed/<run_id>` at it and reset the
   branch back — half-finished work is kept aside rather than mixed in with work
   the user might accept
4. return a `Change`: `base`, `head`, the files, the insertion/deletion tally, and
   the message

The message is the model's own closing sentence, first line, 72 characters — the
same `closing_line()` reading the journal and the run record use, so those three
can never tell a reader three different stories about one run.

## The morning after

`accept(through=None)` is **the one write poieo ever makes to the user's own
branch**:

- refuses if the checkout has *tracked* changes, returning `{"dirty": [...]}`.
  Untracked files are ignored: the run-log store often lives inside the project,
  and an untracked directory is not a reason to refuse the user's own work
- fast-forwards when it can; otherwise a `--no-commit --no-ff` merge, and on
  conflict it reads the conflicted paths, **aborts**, and returns
  `{"conflict": [...]}` — the checkout is left exactly as it was found
- `through` accepts up to one run's commit instead of the whole branch

`discard(since=None)` throws work away **recoverably**: the old tip is parked at
`refs/poieo/discarded/<run_id>` before the branch is reset. Nothing is ever
thrown away for good.

`diff(base, head)` builds what the review screen shows: per-file status and
counts from `--name-status` and `--numstat`, plus the patch, truncated at 400 kB
with a `truncated` flag. A rename reads `R100<tab>old<tab>new`, so the **last**
field is the path worth reporting. Binary files report `-` for both counts; they
still changed, so they are listed with zeroes rather than skipped.

## Rules the module holds

**Everything is synchronous, and every caller wraps it in
`asyncio.to_thread`.** git calls are short but not instant, and the daemon shares
one event loop with the web server — a blocking subprocess on that loop would
stall the event stream for every watcher. The `/api/flows` route gathers the
per-flow review states concurrently for the same reason.

**A `CheckpointError` is never fatal to a flow.** The work still ran. A
repository that cannot be used is logged and the run happens in the folder
directly, with a warning that its changes cannot be reviewed or undone.

**Commits carry poieo's own identity** (`-c user.name=poieo -c
user.email=poieo@localhost`), because automated commits must work on a machine
with no global git config.

**The worktree directory is disposable.** A half-registered worktree — the user
deleted the folder, or `.git/worktrees` went missing — is repaired by pruning,
removing the directory and asking git for a fresh one.

## What it does not protect

The folder itself. That is the work, and it is exposed by definition — isolation
([tools.md](tools.md)) protects everything *outside* it, and this protects the
user's own checkout from the copy. What is inside the copy while the run is
happening is the model's to change; that is the point.
