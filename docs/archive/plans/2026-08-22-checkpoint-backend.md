# Checkpoint Backend Implementation Plan (Plan C)

**Goal:** A daemon flow with a `workdir` works in a private copy of the project, and every run lands as one reviewable change that can be diffed, accepted, or discarded over HTTP — verifiable with curl and `git log` alone.

**Architecture:** A new `poieo.checkpoint` module is the only thing in the codebase that knows git exists. `FlowRunner` asks it for a private worktree before a run and hands that directory to `execute()`, which passes it down as the default workdir for agent nodes; after the run it asks for a commit. The run summary gains a `change` key holding two commit ids, and the web layer grows one read route and two mutation routes on top of it.

**Tech Stack:** Python 3.10, subprocess-invoked `git`, Starlette, pytest + pytest-asyncio (asyncio_mode=auto).

**Spec:** docs/specs/2026-08-22-nightly-review-design.md

## Global Constraints

- **No new dependencies**, pip or otherwise. `git` is invoked as a subprocess; there is no GitPython, no dulwich.
- **`poieo.checkpoint` is the only module that mentions git.** Nothing in `runtime/`, `graph.py`, or `tools/` learns about it. The runtime receives a directory and does not care how it came to exist.
- **The module is synchronous.** git calls are short but not instant, and the daemon shares one asyncio loop with the web server — every caller wraps them in `asyncio.to_thread`. A blocking `subprocess.run` on the loop would stall SSE for every watcher.
- **The user's checkout is never written.** No `checkout`, no `reset`, no `stash`, no commit in the user's worktree — with one exception, the explicit accept, which merges into the branch they are on. Anything else is a bug, not a shortcut.
- **A flow without `workdir` must behave exactly as it does today.** Every new code path is guarded by that being set; the no-workdir suite must stay byte-for-byte green.
- Git identity: commits are made with `-c user.name=poieo -c user.email=poieo@localhost` so a machine without a global git identity still works.
- Test command on this machine (broken global pytest plugin): `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio`. Full suite currently passes **171**.
- Tests use real repositories in `tmp_path`. Mocking git would test the mock.
- Commit messages end with the trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Comment style: sparse, like existing modules — explain constraints, not mechanics.

## Vocabulary guard

The spec fixes what the user sees: **task / work / change**. This plan produces
the backend, so git words are correct in code and in API field names
(`base`, `head`). They must not reach user-facing strings. Any message that a
card could display says *change*, *work*, *accepted*, *discarded* — never
commit, branch, or worktree. The one licensed exception is the accept
preview (`adds 3 commits to main`), which is Plan B's text, not this plan's.

---

### Task 1: `poieo.checkpoint` — the git seam

**Files:**
- Create: `src/poieo/checkpoint.py`
- Test: `tests/test_checkpoint.py`

**Interfaces:**
- Produces: `Change` dataclass (`base`, `head`, `files`, `insertions`, `deletions`), and `Checkpoint(repo: Path, flow: str, poieo_root: Path)` with:
  - `available() -> bool` — git on PATH and `repo` inside a work tree
  - `prepare() -> str` — ensure the branch and the private worktree exist, fast-forward the branch to the user's HEAD when there is no pending work, return the base commit
  - `worktree -> Path` — `poieo_root/worktrees/<flow>`
  - `commit(run_id: str, message: str, *, failed: bool = False) -> Change | None` — `None` when nothing changed; on `failed`, writes `refs/poieo/failed/<run_id>` and leaves the branch where it was
  - `diff(base: str, head: str, *, max_bytes: int = 400_000) -> dict`
  - `pending() -> list[str]` — commits on the branch that the user's HEAD does not contain
  - `accept(through: str | None) -> dict` — `{"accepted": n}`, `{"conflict": [...]}`, or `{"dirty": [...]}`
  - `discard(since: str | None) -> dict` — `{"discarded": n}`, parking the old tip on `refs/poieo/discarded/<run_id>`

- [ ] **Step 1: Write the failing tests**

Build a real repository per test. Suggested helper:

```python
def make_repo(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("hello\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "initial")
    return repo
```

Cases that must exist, one test each:

| test | asserts |
|---|---|
| `test_unavailable_outside_a_repo` | `available()` is False for a plain directory; no exception |
| `test_prepare_creates_private_worktree` | worktree exists, is on `poieo/<flow>`, contains `README.md`, and the user's checkout is still on `main` with a clean status |
| `test_prepare_is_idempotent` | a second `prepare()` reuses the directory and returns the same base |
| `test_commit_records_the_change` | write a file in the worktree, commit, `Change.files == ["new.py"]`, insertions > 0, branch tip == `head`, **user's checkout unchanged** |
| `test_commit_returns_none_when_nothing_changed` | no writes, `commit()` is `None`, branch did not move |
| `test_failed_run_stays_off_the_branch` | `commit(..., failed=True)` leaves the branch tip alone and `refs/poieo/failed/<run_id>` resolves |
| `test_prepare_fast_forwards_to_user_branch` | user commits on `main`, no pending work, `prepare()` moves the flow branch to it |
| `test_prepare_leaves_pending_work_alone` | with a pending commit, a user commit on `main` does **not** move or rebase the flow branch |
| `test_accept_fast_forwards_user_branch` | two pending runs, `accept(None)` → `{"accepted": 2}`, `main` contains both, worktree still usable |
| `test_accept_through_a_run_is_linear` | `accept(head_of_run_1)` takes exactly one, leaving the second pending |
| `test_accept_refuses_a_dirty_checkout` | uncommitted user edit → `{"dirty": ["README.md"]}` and `main` did not move |
| `test_accept_reports_conflict_without_merging` | both sides edit the same line → `{"conflict": [...]}`, `main` unchanged, **no merge left in progress** (`git status` clean) |
| `test_discard_moves_the_branch_back_and_parks_it` | `{"discarded": n}`, branch back at the user's tip, `refs/poieo/discarded/<run_id>` still resolves to the old tip |
| `test_diff_reports_files_and_truncates` | file list with per-file insert/delete counts; a patch over `max_bytes` comes back with `truncated: True` |

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_checkpoint.py -q -p asyncio`
Expected: FAIL with `ModuleNotFoundError: No module named 'poieo.checkpoint'`

- [ ] **Step 3: Implement**

Shape of the module — one private `_git` helper, everything else on top of it:

```python
def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=poieo", "-c", "user.email=poieo@localhost", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise CheckpointError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout
```

Notes that will bite otherwise:

- `git worktree add` needs the branch to exist first; create it with `git branch <b> HEAD` when `git rev-parse --verify` fails.
- A worktree directory that exists but is not registered (user deleted `.git/worktrees`, or the reverse) must be repaired: `git worktree prune`, then recreate. Treat the directory as disposable.
- Conflict detection without leaving a mess: `git merge --no-commit --no-ff`, and on failure `git merge --abort` before returning the conflicted paths from `git diff --name-only --diff-filter=U`.
- `--numstat` gives per-file insertions/deletions; binary files report `-`, which must not crash the parser.
- Windows: worktree paths under `.poieo/` stay relative to the store root, and every path handed to git is `as_posix()`.

- [ ] **Step 4: Run tests to verify they pass**
- [ ] **Step 5: Full suite** — `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio`
- [ ] **Step 6: Commit** — `feat: checkpoint module tracks a flow's changes in a private worktree`

---

### Task 2: flow-level `workdir` reaches agent nodes

**Files:**
- Modify: `src/poieo/daemon/config.py` (`FlowSpec.workdir`)
- Modify: `src/poieo/runtime/context.py` (`RunContext.workdir`)
- Modify: `src/poieo/runtime/executor.py` (`execute(workdir=...)`, `preflight`)
- Modify: `src/poieo/runtime/nodes.py` (agent node falls back to the run's workdir)
- Modify: `src/poieo/graph.py` (agent node no longer *requires* its own workdir)
- Test: `tests/test_runtime.py`, `tests/test_daemon_config.py`

**Interfaces:**
- Consumes: `execute(..., workdir: Path | None = None)`.
- Produces: an agent node with no `workdir:` of its own runs in the run's workdir; a node that declares one still wins.

Why this exists: a filesystem path is *physical* information, and the graph is
the *logical* layer (principle 1). A graph that hardcodes `/home/me/project`
cannot be moved. After this task the graph describes the work and the flow says
where it happens.

- [ ] **Step 1: Write the failing tests**
  - `test_agent_node_inherits_the_run_workdir` — graph with no `workdir:`, `execute(workdir=tmp)`, tool calls land in `tmp`
  - `test_node_workdir_overrides_the_run_workdir` — the node's own value wins
  - `test_preflight_rejects_an_agent_node_with_nowhere_to_work` — no node workdir, no run workdir → `SpecError` **before** any provider call
  - `test_flow_spec_accepts_workdir` — the daemon config parses and resolves it relative to the config file
- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement**
  - `graph.py:121` — drop the hard requirement; keep template validation when the key is present
  - `preflight()` gains the run workdir and raises `SpecError` naming the node when neither source supplies one, preserving "fail before spending tokens"
  - `nodes.py:173` — `spec.workdir` rendered, else `ctx.workdir`, else the preflight error already fired
- [ ] **Step 4: Run tests** — [ ] **Step 5: Full suite** — [ ] **Step 6: Commit**
  `feat: a flow says where the work happens, so graphs stop hardcoding paths`

---

### Task 3: the run boundary — private copy in, change out

**Files:**
- Modify: `src/poieo/daemon/service.py` (`FlowRunner`)
- Modify: `src/poieo/runtime/context.py` (`RunResult.change`, `summary()`)
- Test: `tests/test_daemon_checkpoint.py`

**Interfaces:**
- Produces: `RunResult.change: dict | None`; `summary()["change"]` present only when a change was committed; a `run_change` event on the store.

- [ ] **Step 1: Write the failing tests** (mock binding, a real repo as `workdir`)
  - `test_run_works_in_the_private_copy_not_the_users_folder` — after a run that writes a file, the user's checkout is clean and the file is not there; the flow branch has it
  - `test_summary_carries_the_change` — `summary()["change"]` has `base`, `head`, `files`, `insertions`, `deletions`
  - `test_run_change_event_is_emitted` — the event stream contains one `run_change` with the same ids
  - `test_no_change_is_not_a_failure` — a run that writes nothing: status is still `completed`, no `change` key, nothing committed
  - `test_failed_run_does_not_advance_the_branch` — branch tip unmoved, run still recorded
  - `test_flow_without_workdir_is_untouched` — no git anywhere, summary identical to today's
- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement** — in `FlowRunner.run()`, around the existing `execute(...)`:

```
checkpoint = Checkpoint(workdir, flow.spec.name, config.store) if flow.spec.workdir else None
if checkpoint and await asyncio.to_thread(checkpoint.available):
    base = await asyncio.to_thread(checkpoint.prepare)
    run_workdir = checkpoint.worktree
...
result = await execute(..., workdir=run_workdir)
...
if checkpoint:
    change = await asyncio.to_thread(
        checkpoint.commit, result.run_id, summary_line(result), failed=result.status != "completed"
    )
```

- The commit message's first line is the model's own one-line summary when the
  graph produced one, else `poieo <flow> <run_id>`. This is what the work list
  shows, so it is worth getting from the run rather than templating.
- A `CheckpointError` must never kill the flow (principle 5): log it, record the
  run without a change, keep going. A broken repository is not a reason to stop
  working at 3am — it is a reason for the card to say changes cannot be reviewed.
- [ ] **Step 4: Run tests** — [ ] **Step 5: Full suite** — [ ] **Step 6: Commit**
  `feat: each run lands as one reviewable change in a private copy`

---

### Task 4: `GET /api/runs/{run_id}/diff`

**Files:**
- Modify: `src/poieo/web/server.py`
- Test: `tests/test_web_api.py`

**Interfaces:**
- Produces: `{run_id, base, head, files: [{path, status, insertions, deletions}], patch, truncated}`; 404 when the run is unknown, and `{"change": null}` with 200 when the run simply made no change (that is information, not an error).

- [ ] **Step 1: Write the failing tests** — a run with a change returns the file list and a patch; a run without one returns `change: null`; an unknown id is 404; an oversized patch comes back `truncated: true` with the file list intact.
- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement** — read `base`/`head` from the run summary in the index, then `await asyncio.to_thread(checkpoint.diff, base, head)`. Nothing is cached; two commit ids regenerate it on demand, which is the point.
- [ ] **Step 4: Run tests** — [ ] **Step 5: Full suite** — [ ] **Step 6: Commit**
  `feat: the observation API serves a run's diff on demand`

---

### Task 5: accept and discard

**Files:**
- Modify: `src/poieo/web/server.py`
- Test: `tests/test_web_api.py`

**Interfaces:**
- Produces: `POST /api/flows/{flow}/accept` body `{through_run_id?}`; `POST /api/flows/{flow}/discard` body `{from_run_id?}`. Also extends `GET /api/flows` with `pending: n` so the board can show something to review without asking per run.

- [ ] **Step 1: Write the failing tests**
  - accept with pending work → `{"accepted": n}`, user branch advanced
  - accept through a specific run → only that far
  - accept with a dirty user checkout → 409 `{"dirty": [...]}`, nothing moved
  - accept with a conflict → 409 `{"conflict": [...]}`, nothing moved, repository not mid-merge
  - discard → `{"discarded": n}`, branch back, work still reachable through the parked ref
  - both routes on an unknown flow → 404
  - **`GET` on either route → 405**, so a crawler or a prefetch can never mutate
- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement** — routes declared `methods=["POST"]`. These are the only two mutations in the web layer; a comment at the route table should say so, because the next person will otherwise read the file as read-only and add a third.
- [ ] **Step 4: Run tests** — [ ] **Step 5: Full suite** — [ ] **Step 6: Commit**
  `feat: accept or discard a flow's pending work over the API`

---

### Task 6: preflight, example, and README

**Files:**
- Modify: `src/poieo/cli.py` (`validate`)
- Modify: `examples/poieo.yaml`
- Modify: `README.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**
  - `poieo validate` on a flow whose `workdir` is missing → fails at load, not at 3am
  - `poieo validate` on a flow whose `workdir` exists but is not a repository → succeeds with a **warning** naming the consequence ("changes here can't be reviewed or undone"), because it is a degraded mode, not an error
  - git absent from PATH → the same warning shape, never a crash
- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement** — plus a `workdir:` line on the example's agent flow, and a README section that states the user-facing contract in the spec's three words and no others.
- [ ] **Step 4: Run tests** — [ ] **Step 5: Full suite** — [ ] **Step 6: Commit**
  `docs: flows say where they work, and what happens to the changes`

---

## Done means

- A daemon flow with `workdir` runs all night without the user's checkout ever changing — `git status` in their project is clean in the morning and they are on the branch they left.
- `curl 127.0.0.1:8484/api/runs/<id>/diff` shows what one run did.
- `curl -X POST 127.0.0.1:8484/api/flows/<flow>/accept` puts it in their project; `git log` proves it.
- Discarding is recoverable: the parked ref still resolves afterwards.
- A flow with no `workdir` behaves exactly as it did before this plan, and the suite proves it.
- Nothing outside `poieo/checkpoint.py` mentions git.
