# Container Isolation Implementation Plan (Plan D)

**Goal:** A task with an `isolation` block runs its shell commands inside a container that can see only its folder — provable by one pair of tests where the same command succeeds without isolation and fails with it.

**Architecture:** `poieo.tools.docker` is the only module that knows Docker exists. `LocalExecutor` and `DockerExecutor` are async context managers behind one factory; `runtime/nodes.py` acquires its executor from that factory and never learns which it got. A box outlives a run, so `FlowRunner` owns it — the same object that owns the task's private working copy. File tools stay on the host, confined by `resolve_path`; only `run_command` moves inside.

**Tech Stack:** Python 3.10, subprocess-invoked `docker`, pytest + pytest-asyncio (asyncio_mode=auto).

**Spec:** docs/specs/2026-08-22-container-isolation-design.md

## Revision, 2026-08-23

Tasks 1 and 2 shipped against the original design, where a box lived exactly as long as one agent node. The user asked what the boundary should be; a survey of the field (recorded in the spec) said nobody runs a container per command, and that container users keep one alive per conversation or per instance.

poieo's task accumulates on purpose — its journal is re-read before every run, its private working copy persists — so **the box is now per task, kept between runs**. Tasks 3 onward are written against that. Nothing in Tasks 1 or 2 has to be undone: the executor still attaches to a container, it just no longer creates the one it attaches to.

## Depends on

**Plan C is not merged yet** (`src/poieo/checkpoint.py` is absent from `main`; the `checkpoint-backend` branch has all six of its tasks done). Task 3 puts a second durable, task-scoped thing on `FlowRunner`, which is exactly where Plan C puts the private worktree.

Land Plan C first, then **reuse the shape it built — do not invent a second one.** If the worktree and the box arrive at `AgentNode.run` by two different routes, whoever adds a third will have to pick, and will pick wrong.

## Global Constraints

- **No new dependencies**, pip or otherwise. `docker` is invoked as a subprocess; there is no docker-py, no podman shim.
- **`poieo.tools.docker` is the only module that names Docker.** Not `nodes.py`, not `graph.py`, not `files.py`, not `shell.py`, not `task.py`. The factory in `tools/__init__.py` may import it lazily; nothing else may import it at all. `daemon/service.py` may hold a box, but only through a handle with no Docker words on it.
- **A task without `isolation` must behave exactly as it does today.** Every new code path is guarded by that block being present. The no-isolation suite must stay byte-for-byte green.
- **No fallback, ever.** If isolation is requested and cannot be provided, the caller gets an error. A code path that silently runs unsandboxed is the one bug this whole slice exists to prevent — worse than not shipping.
- Docker calls made while the loop is running are async (`asyncio.create_subprocess_exec`), like `shell.py`. The daemon shares one loop with the web server; a blocking `subprocess.run` would stall SSE for every watcher. Preflight runs before the loop starts and may be synchronous.
- Tests use real containers. Mocking `docker` would test the mock. They skip with an explicit reason when the daemon is unreachable, so a machine without Docker still gets an honest count.
- **Baseline:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **235 passed, 0 failed** at `df0b3f8` with Tasks 1–2 applied. The suite is fully green; anything red is yours.
- Comment style: sparse, like the existing modules — explain constraints, not mechanics.
- Commit messages end with the trailer naming the model that wrote them, per CLAUDE.md.

## Vocabulary guard

The spec fixes what the user reads: a task is **isolated** or it is not, and the idea underneath is **reach**. This plan produces backend and configuration, so Docker words are correct in code, in field names, and in configuration errors. They must not reach a string a card could display — not *container*, not *image*, not *mount*, not *exec*.

---

### Task 1: `DockerExecutor` and the escape test — **done** (PR #1, `f7f9283`)

`src/poieo/tools/docker.py` and `tests/test_tools_docker.py`. `docker_available()`, `image_present()`, and a `DockerExecutor` with the same `definitions()`/`execute()` as `LocalExecutor`. 16 tests against real `alpine:3.20` containers; the escape pair verified by hand as well as by assertion.

Two things recorded there that no test would have explained:

- The idle command is `sleep 2147483647`, not `sleep infinity`. `infinity` is a GNU coreutils extension. Busybox 1.36.1 does accept it — measured — but older builds reject it, and then the container exits instantly and every later `docker exec` fails with a confusing "is not running".
- The bind-mount source must be an **absolute, resolved** path. Given a relative or `~`-prefixed one, Docker silently creates an empty *named volume*: the container starts, `/work` is empty, and the model reports the project does not exist.

### Task 2: the lifecycle seam and the factory — **done** (PR #2, `dc1c709`)

A shared `Executor` base owns tool lookup, failure-to-text and a no-op lifecycle. `make_executor(workdir, toolsets, isolation=None)` is the one place that picks a subclass, with the Docker import inside the isolation branch. `AgentNode.run` acquires its executor with `async with` and names no backend.

---

### Task 3: the box, and who owns it

**Files:**
- Modify: `src/poieo/tools/docker.py` (split creation from attachment)
- Modify: `src/poieo/tools/__init__.py` (`make_executor` takes a box)
- Modify: `src/poieo/daemon/service.py` (`FlowRunner` holds one)
- Test: `tests/test_tools_docker.py`, `tests/test_daemon.py`

**Interfaces:**
- Produces, in `tools/docker.py`:
  - `Box(key: str, workdir: Path, isolation: Isolation)` — owns at most one container.
    - `async ensure() -> str` — the container id, starting it if missing or dead. Idempotent; two runs in a row get the same id.
    - `async remove() -> None` — never raises.
    - `matches(isolation) -> bool` — false when the image, network or user changed.
    - `last_used: datetime` — what the idle sweep reads.
  - `async sweep(older_than: timedelta) -> int` — removes boxes whose `poieo.task` label marks them idle past the cutoff, including ones this process did not start.
- `DockerExecutor` gains `box: Box | None`. With a box it **attaches**: `__aenter__` calls `ensure()`, `__aexit__` does nothing. Without one it behaves exactly as today — creates on enter, removes on exit — which is the one-shot `poieo run` path.
- `make_executor(workdir, toolsets, isolation=None, box=None)`.

**The ownership rule.** `FlowRunner` already drives one task and outlives every run of it. It holds the box, creates it lazily on the first run that needs one, drops it when the daemon stops or the task's `isolation` stops matching. Nothing above `FlowRunner` and nothing below `make_executor` knows a box exists; what travels between them is an opaque handle.

**Do not tear a box down in `__aexit__` when it was handed in.** That inversion — the borrower destroying the lender's object — is the bug this task exists to avoid, and it will look correct in every single-run test. The reuse test below is the one that catches it.

- [ ] **Step 1: Write the failing tests**

```python
async def test_two_runs_share_one_box(tmp_path): ...              # THE test: same container id
async def test_a_file_written_by_the_first_run_survives(tmp_path): ...  # what reuse is for
async def test_ensure_restarts_a_box_that_died(tmp_path): ...
async def test_a_changed_image_does_not_match(tmp_path): ...
async def test_remove_is_safe_to_call_twice(tmp_path): ...
async def test_an_attached_executor_does_not_remove_the_box(tmp_path): ...   # the inversion
async def test_a_one_shot_executor_still_removes_its_own(tmp_path): ...
async def test_the_sweep_removes_an_idle_box_and_spares_a_fresh_one(tmp_path): ...
async def test_the_daemon_drops_its_boxes_when_it_stops(tmp_path): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the full suite**
- [ ] **Step 5: Commit** — `feat: a task keeps one box between its runs`

---

### Task 4: a task opts in

**Files:**
- Modify: `src/poieo/task.py` (`TaskSpec.isolation`)
- Modify: `src/poieo/daemon/config.py` (`FlowSpec.isolation`, and the task -> flow expansion)
- Test: `tests/test_task.py`, `tests/test_daemon.py`

**Interfaces:**
- Produces: an `isolation` block on a task card and on a hand-written flow, parsed into the `Isolation` dataclass Task 2 defined. `image` required, `network` defaulting to `none`, `user` optional, `extra="forbid"`.

A task is sugar that expands into a flow plus a one-node graph, so `isolation` rides that expansion like every other task key. Read `task.py`'s existing expansion before adding to it; the `_NODE_KEYS` list is where a key that describes the generated node goes, and `isolation` is **not** one of those — it describes the task, and survives `poieo eject`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_task_card_parses_an_isolation_block(): ...
def test_image_is_required_when_the_block_is_present(): ...
def test_network_defaults_to_none(): ...
def test_an_unknown_isolation_key_is_rejected(): ...
def test_isolation_survives_eject(): ...              # it is not a node key
def test_a_task_without_isolation_is_unchanged(): ...
async def test_the_setting_reaches_the_agent_node(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the tests to verify they pass**
- [ ] **Step 5: Commit** — `feat: a task can ask to run isolated`

---

### Task 5: preflight — fail at launch, not at 3am

**Files:**
- Modify: `src/poieo/daemon/config.py` (`load_flows`)
- Modify: `src/poieo/cli.py` (`check`)
- Test: `tests/test_daemon.py`, `tests/test_cli.py`

Every task declaring `isolation` is checked when the config loads: docker on PATH, the daemon answering, and the named image present locally. A missing image prints the fix verbatim — `docker pull python:3.12-slim` — because that is the next thing the user will type.

Cache by image within one load, so ten tasks sharing an image cost one check. This is the slowest preflight in the codebase; what buys the cost is that a task whose image was pruned last week must not discover it at 3am.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_task_with_isolation_fails_to_load_without_docker(monkeypatch): ...
def test_a_missing_image_names_the_pull_command(monkeypatch): ...
def test_the_same_image_is_only_checked_once(monkeypatch): ...
def test_tasks_without_isolation_never_touch_docker(monkeypatch): ...   # no ping at all
def test_check_reports_isolation_readiness(): ...
```

`docker_available` is monkeypatched here rather than driven for real: this task tests poieo's reaction to an answer, not Docker itself. Task 1 is where the real thing is exercised.

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the tests to verify they pass**
- [ ] **Step 5: Commit** — `feat: isolation is verified when the config loads`

---

### Task 6: `poieo run --isolate` and `poieo reset`

**Files:**
- Modify: `src/poieo/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- `poieo run --isolate <image>` — a one-shot run in an ephemeral box, through the same preflight. No box outlives it; there is no next run to keep one for.
- `poieo reset <task>` — throw away that task's box. The spec makes this the explicit escape hatch and the thing to suggest when a task starts behaving oddly, so it must work whether or not a daemon is running, and say plainly that nothing in the task's folder was touched.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_isolate_builds_an_isolation_spec(monkeypatch): ...
def test_run_isolate_preflights_before_the_first_model_call(monkeypatch): ...
def test_run_without_isolate_never_touches_docker(monkeypatch): ...
def test_reset_removes_the_box_and_says_the_folder_is_untouched(): ...
def test_reset_on_a_task_with_no_box_is_not_an_error(): ...
```

- [ ] **Step 2: Run the tests to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the tests to verify they pass**
- [ ] **Step 5: Commit** — `feat: poieo run --isolate, and poieo reset`

---

### Task 7: document it and show it working

**Files:**
- Modify: `README.md`
- Modify: `DESIGN.md` (capability layers and safety boundaries — status only)
- Modify: `examples/tasks/` (one card, isolation on, documented as needing a pull)

- [ ] **Step 1: The example**

A task card with an `isolation` block, and a comment saying it needs `docker pull python:3.12-slim` first. It must not break `poieo tasks` on a machine without Docker — check what the loader does before deciding whether it ships enabled.

- [ ] **Step 2: README**

Use the spec's *reach* wording, not Docker's. Say what changes (a command it runs stays inside the folder), what does not (file tools were already confined), that the network is off unless asked for, and that the image must already exist locally. Then the honest half, in its own short paragraph: the folder itself is exposed by definition, prompts still leave the host, and a container shares the host kernel — it is a strong boundary, not an absolute one.

End with the question the user is actually deciding: *can you predict every command this prompt will run, overnight, with this model?*

- [ ] **Step 3: DESIGN.md**

The safety-boundaries section says container isolation is opt-in; that is now true rather than planned. Change the status, not the argument. Keep the file under 500 lines and at the logic level.

- [ ] **Step 4: The whole suite, both ways**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio
```

Then stop Docker Desktop and run it again. Expected: green both times — the container tests skip with a reason in the second run, and nothing else changes. Paste both summary lines into the report.

- [ ] **Step 5: End-to-end by hand**

Run an isolated task twice against the mock binding. Confirm: the second run reuses the first run's box, a file the first run's shell wrote is still there, and the tool calls show in the browser. Then set the prompt to read something above the folder and confirm the model gets a tool error back **and keeps working** — the model must see a failure, not have the run die.

- [ ] **Step 6: Commit** — `docs: container isolation, opt-in per task`

---

## Done means

- A task with `isolation` runs shell commands that cannot read one directory above its folder; the same task without it can. Both are tests.
- Two runs of one task share a box, and what the first installed is there for the second. Deleting the box is always safe and the next run rebuilds it.
- `grep -ri docker src/poieo --include=*.py` matches `tools/docker.py`, one lazy import in `tools/__init__.py`, and the preflight call in `daemon/config.py`. Nothing else.
- A machine without Docker runs the full suite green and every existing task unchanged.
- A task whose image is missing fails when the config loads, naming the `docker pull` that fixes it.
- The README says plainly what isolation does **not** protect.
- Adding Podman, or an OS-level sandbox, is one new module and one factory branch — no runtime change, no config reshuffle.
