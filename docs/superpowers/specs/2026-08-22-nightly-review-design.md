# Nightly Review Design

**Date:** 2026-08-22
**Status:** Approved for planning
**Roadmap:** the morning half of the web control plane

## Goal

The user wakes up, opens the board, and answers one question: **what did it do
last night, and do I want it?**

Every run of a flow with hands is captured as one reviewable change. The board
shows the change; two buttons take it or throw it away. Nothing the model
writes reaches the user's own files until they say so.

This closes the loop the observation slice opens. Observation answers *what is
it doing right now*; this answers *what did it do, and is it any good*.

## Decisions already made (with the user)

- **Work happens in a private copy.** Each flow gets its own git worktree under
  `.poieo/worktrees/<flow>`. The user's checkout is never switched, never
  dirtied, never touched until they accept.
- **One run = one change.** A commit at the run boundary. The unit you undo is
  the unit that ran.
- Successful runs advance the flow's branch; failed runs are parked where the
  user never sees them.
- **The web page is the only surface for v1.** CLI equivalents are cheap once
  the API exists, and explicitly later.
- Accept and discard are the **only two mutations** the web may perform in this
  slice. Everything else stays read-only.
- The machinery is hidden. See *Vocabulary* — it is the binding constraint on
  this design, not a presentation detail.

## Out of scope

- Task-card CRUD, pause/resume, run-now — the other half of the control plane.
- Partial acceptance. Accept and discard operate on whole runs, never on files
  or hunks.
- Any git operation on the user's branch that they did not ask for: no rebase,
  no force, no history rewriting, ever.
- Remotes. No push, no PR, no fetch.
- Snapshotting non-git workdirs. A folder that is not a repository gets an
  offer to become one, not a second snapshot mechanism.

## Vocabulary

The user learns three words. That is the whole model.

| word | means |
|---|---|
| **task** | a name, a prompt, and a folder. One card. |
| **work** | one run of that task. It **succeeded**, **failed**, or **found nothing to do**. |
| **change** | the files one piece of work touched. You look at it, then **accept** or **discard** it. |

Words that must never appear in the interface: commit, sha, branch, worktree,
ref, merge, HEAD, stash, run id, event.

**The rule: hide the mechanism, never the result.** Git vocabulary is allowed
in exactly one place — the moment the user's own repository is about to change,
the accept button says what will happen to it:

```
[ Accept ]   adds 3 commits to main
[ Discard ]  throws this work away
```

Everywhere else, silence. A failed run parked on an internal ref reads as
"discarded". A private worktree is never named at all.

## Storage model

```
<workdir>/                        the user's checkout — read by poieo, written never
.poieo/worktrees/<flow>/          the private copy the model actually works in
refs/heads/poieo/<flow>           accepted-or-pending work, one commit per run
refs/poieo/failed/<run_id>        a failed run's changes, kept but off the branch
refs/poieo/discarded/<run_id>     what a discard threw away, kept so nothing is lost
```

The worktree is derived state: delete `.poieo/worktrees/` and the next run
rebuilds it. The branch and the refs are the durable part, and git already
knows how to store them compactly.

**Acceptance state is derived, not recorded.** A run's change is *accepted* if
its commit is an ancestor of the user's current branch, *discarded* if it is no
longer reachable from the flow branch, and *pending* otherwise. Nothing has to
be mutated after the fact, which keeps the append-only run index append-only
and keeps git the single source of truth.

## Run lifecycle

```
1. workdir resolved      FlowSpec.workdir; absent -> no change tracking, card says so
2. private copy ready    create or reuse .poieo/worktrees/<flow> on poieo/<flow>
3. base recorded         the commit the work starts from
   -- graph runs; agent nodes read and write inside the private copy --
4. nothing changed?      no commit; the work is recorded as "found nothing to do"
5. succeeded             commit; poieo/<flow> advances
6. failed                commit to refs/poieo/failed/<run_id>; the branch does not move
7. summary               the run summary carries base, head, files, insertions, deletions
8. event                 a `run_change` event so a watching board updates live
```

**Catching up with the user.** At step 2, if the flow branch has no pending
work and the user's branch has moved ahead, the flow branch fast-forwards to
it — the model starts from the user's latest. If there *is* pending work, the
branch is left alone and the card says the work is based on an older version of
the project. poieo never rebases pending work to make this tidier; a surprising
rebase at 3am is worse than a stale base.

**Uncommitted user work is not included.** The private copy is made from the
last commit, so anything the user has not committed simply is not there. This
is a divergence from aider, which commits the user's dirty files before
editing; with an isolated worktree there is no reason to touch their files at
all. The card states it once, plainly.

## Accept and discard

**Accept** merges the flow branch into whatever branch the user's checkout is
on. Fast-forward when possible, a merge commit otherwise.

- Default is card-level: *accept last night's work* — everything pending.
- Run-level is *accept up to this work*, which is linear and needs no
  cherry-picking. There is deliberately no "accept only this one".
- Conflict: nothing is merged. The card names the conflicting files and says
  the user changed them too. poieo does not attempt resolution and never
  leaves the repository mid-merge.
- The user's checkout must be clean. If it is not, the card asks them to
  commit or stash first, in those words, because that is the one moment their
  own repository is at stake.

**Discard** moves the flow branch back to the last accepted point.

- Default is card-level: *discard last night's work*.
- Run-level is *discard from this work onward* — the same linear rule.
- What is discarded is parked on `refs/poieo/discarded/<run_id>` first. The
  interface says "thrown away"; the bytes survive, because a wrong click at
  8am should not be fatal.

## Failure handling

| situation | behaviour |
|---|---|
| workdir is not a git repository | the flow still runs, changes are untracked. Card: "changes here can't be reviewed or undone" plus a **make this undoable** button that runs the initial setup. |
| workdir does not exist | a configuration error, so it fails at load time like every other one (principle 5). |
| git is not installed | the same — reported by `poieo validate`, not at 3am. |
| private worktree missing or broken | rebuilt at run start; it is derived state. |
| two flows share a workdir | each gets its own worktree and branch; they only meet when both are accepted, which is ordinary git. |
| first run has no build environment | the private copy starts without `node_modules`, `.venv`, and friends. It persists across runs, so this is a one-time cost the flow's own prompt handles. Documented, not automated. |

## API additions

Three routes on top of the observation API. The first is read-only; the other
two are this slice's only mutations.

| route | returns |
|---|---|
| `GET /api/runs/{run_id}/diff` | `{run_id, base, head, files: [{path, status, insertions, deletions}], patch}` — `patch` omitted above a size cap, with `truncated: true` |
| `POST /api/flows/{flow}/accept` | body `{through_run_id?}` -> `{accepted: n}`, or `{conflict: [paths]}`, or `{dirty: [paths]}` |
| `POST /api/flows/{flow}/discard` | body `{from_run_id?}` -> `{discarded: n}` |

A diff is never stored. Two commit ids are enough to regenerate it on demand,
which keeps the run log's growth unrelated to the size of the work.

Run summaries gain one key:

```
change: {base, head, files, insertions, deletions}
```

Absent when the flow has no workdir, or when the run changed nothing. The board
derives *pending / accepted / discarded* from git, as described above.

## The review screen

Three levels, no more.

1. **Board** — one card per task. Live status on top; underneath, last night in
   one line: `8 works · 5 succeeded · 2 failed · 1 found nothing · +61 / -22`.
   Failed work is counted here but not listed.
2. **Work list** — newest first, one row each: time, outcome, one-line size, and
   the model's own one-line summary. Failed rows are collapsed by default.
3. **One piece of work** — the diff on the left, folded by file; the run's
   timeline on the right (nodes, tool calls, what the model said). Accept and
   discard live here and on the card.

The skin contract is untouched: this is shared React UI outside the skins,
alongside the detail drawer.

## Testing

- The `checkpoint` module against real repositories in `tmp_path` — git is
  cheap enough to test for real, and mocking it would test nothing worth
  testing. Cases: fresh repo, no changes, failed run, user branch moved ahead,
  pending work blocking the fast-forward, conflict on accept, dirty checkout.
- Runs with no workdir must be byte-for-byte unaffected: the whole feature is a
  no-op without one.
- API: Starlette `TestClient` over a temporary repository for diff, accept,
  discard, and every refusal path.
- Frontend: reducer fixtures for the derived accepted/pending/discarded state
  and for the night rollup.

## Implementation split

- **Plan C — checkpoint backend**: `poieo.checkpoint`, flow-level `workdir`,
  run lifecycle hooks, the `change` summary key, the three routes. Verifiable
  with curl and `git log` alone.
- **Plan B (amended) — the review screen**: work list, diff viewer, accept and
  discard, the night rollup on the card. The `atelier` skin moves behind them.
