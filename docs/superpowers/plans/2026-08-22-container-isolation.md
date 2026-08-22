# Container Isolation Implementation Plan (Plan D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A flow with an `isolation` block runs its shell commands inside a container that can see only the working directory — provable by one pair of tests where the same command succeeds without isolation and fails with it.

**Architecture:** A new `poieo.tools.docker` module is the only thing in the codebase that knows Docker exists. `LocalExecutor` and `DockerExecutor` become async context managers behind one factory; `runtime/nodes.py` acquires its executor from that factory with `async with` and never learns which it got. File tools stay on the host, confined by `resolve_path` exactly as today; only `run_command` moves inside the box.

**Tech Stack:** Python 3.10, subprocess-invoked `docker`, pytest + pytest-asyncio (asyncio_mode=auto).

**Spec:** docs/superpowers/specs/2026-08-22-container-isolation-design.md

## Depends on, and conflicts with

**Plan C touches the same function this plan touches.** Its Task 2 ("flow-level `workdir` reaches agent nodes") edits `AgentNode.run` in `src/poieo/runtime/nodes.py` where the workdir is resolved; this plan's Task 2 edits the next statement, where the executor is constructed. That is one small conflict in one function, not a design collision.

Land Plan C first. Then, in Task 3, **reuse whatever mechanism Plan C built to carry a flow-level value down to agent nodes — do not invent a second one.** If two parallel settings arrive at `AgentNode.run` by two different routes, the next person to add a third will have to pick, and will pick wrong.

Everything else is untouched ground: Plan C's constraints promise that nothing in `tools/` learns about git, and Plan B is frontend-only.

## Global Constraints

- **No new dependencies**, pip or otherwise. `docker` is invoked as a subprocess; there is no docker-py, no podman shim.
- **`poieo.tools.docker` is the only module that names Docker.** Not `nodes.py`, not `graph.py`, not `files.py`, not `shell.py`. The factory in `tools/__init__.py` may import it lazily; nothing else may import it at all.
- **A flow without `isolation` must behave exactly as it does today.** Every new code path is guarded by that block being present. The no-isolation suite must stay byte-for-byte green.
- **No fallback, ever.** If isolation is requested and cannot be provided, the caller gets an error. A code path that silently runs unsandboxed is the one bug this whole slice exists to prevent — it would be worse than not shipping.
- Docker calls are async (`asyncio.create_subprocess_exec`), like `shell.py`. The daemon shares one loop with the web server; a blocking `subprocess.run` would stall SSE for every watcher.
- Tests use real containers. Mocking `docker` would test the mock. They skip with an explicit reason when the daemon is unreachable, so a machine without Docker still gets an honest count.
- **Baseline on this machine:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio` → **171 tests, 170 pass.** `tests/test_cli.py::test_daemon_once_runs_each_flow_and_logs_them` fails whenever a `poieo daemon` is already listening on 8484, because it invokes the CLI without `--no-web` and tries to bind the real port. That is a pre-existing test-isolation defect, unrelated to this plan; do not "fix" it here and do not let it mask a regression.
- Comment style: sparse, like the existing modules — explain constraints, not mechanics.
- Commit messages end with the trailer naming the model that wrote them, per CLAUDE.md.

## Vocabulary guard

The spec fixes what the user reads: **isolated** / **not isolated**. This plan produces backend and configuration, so Docker words are correct in code, in field names, and in configuration errors. They must not reach a string a task card could display. Any message about a run says *isolated*, never *container* or *image*.

---

### Task 1: `DockerExecutor` and the escape test

**Files:**
- Create: `src/poieo/tools/docker.py`
- Test: `tests/test_tools_docker.py`

**Interfaces:**
- Consumes: `Tool`, `ToolError`, `ToolResult`, `TOOLSETS` from `poieo.tools`; `FILES_TOOLS` unchanged.
- Produces:
  - `docker_available() -> tuple[bool, str]` — `(False, reason)` when docker is off PATH or the daemon does not answer. The reason is a configuration string, not an interface string.
  - `image_present(image) -> bool`
  - `DockerExecutor(workdir, toolsets, *, image, network="none", user=None, labels=None)` with the same `definitions()` and `execute()` as `LocalExecutor`, plus `__aenter__` / `__aexit__`.

**How it is built.** `DockerExecutor` assembles the same tool dict `LocalExecutor` does, then replaces the `run_command` entry with one bound to its container. File tools are the host implementations, untouched — the workdir they write is the bind-mount source, so the container sees each write immediately.

`__aenter__` runs `docker run -d --rm -v <workdir>:/work -w /work --network <network> [--user <user>] --label poieo.run_id=<id> <image> sleep 2147483647` and keeps the container id. `__aexit__` runs `docker rm -f <id>` and must not raise — teardown failure is logged, never propagated over the exception that caused it.

**Two details that will not show up as a red test.**

- The idle command is `sleep 2147483647`, not `sleep infinity`. `infinity` is a GNU coreutils extension; busybox `sleep` — which is what `alpine` and most slim images ship — rejects it, so the container would exit immediately and every later `docker exec` would fail with a confusing "not running". A finite number works on both. The image's only requirement is a shell at `/bin/sh`, and that belongs in the README.
- The bind-mount source must be passed as an **absolute, resolved** path. On Windows, `Path.resolve()` yields `C:\Users\...`, which Docker Desktop accepts, but a relative or `~`-prefixed path silently becomes a *named volume* instead of a mount — the container then starts fine, sees an empty `/work`, and the model reports that the project is empty. Resolve before building the argument, and assert the mount is a directory.

`run_command` becomes `docker exec -w /work <id> sh -c <command>`, keeping `shell.py`'s existing `_MAX_TIMEOUT`, output cap, and `exit code: N` result shape. On timeout, the exec is killed and the container is still torn down by `__aexit__`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tools_docker.py`, guarded by a module-level skip when `docker_available()` is false:

```python
async def test_a_command_cannot_read_above_the_workdir(tmp_path): ...   # THE test
async def test_the_same_command_succeeds_without_isolation(tmp_path): ...  # the control
async def test_network_is_off_by_default(tmp_path): ...
async def test_write_file_then_cat_sees_the_write(tmp_path): ...
async def test_the_reverse_direction_also_agrees(tmp_path): ...
async def test_the_container_is_gone_after_aexit(tmp_path): ...
async def test_the_container_is_gone_when_the_body_raises(tmp_path): ...
async def test_a_timed_out_command_still_tears_down(tmp_path): ...
async def test_an_unknown_tool_is_an_error_not_a_crash(tmp_path): ...
```

The first two are a pair and must be read as one: a secret file is written one level *above* `tmp_path/work`, and `run_command("cat ../secret")` must fail isolated and succeed unisolated. If both pass, the feature does nothing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_tools_docker.py -q -p asyncio`
Expected: FAIL — `src/poieo/tools/docker.py` does not exist. If instead they all SKIP, Docker Desktop is not running; start it before continuing, because a skipped escape test proves nothing.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Paste the run into the report, and state plainly whether it ran or skipped.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: docker-backed executor confines the shell to the workdir"
```

---

### Task 2: the lifecycle seam and the factory

**Files:**
- Modify: `src/poieo/tools/__init__.py`
- Modify: `src/poieo/runtime/nodes.py`
- Test: `tests/test_tools.py` (append)

**Interfaces:**
- Produces:
  - `LocalExecutor.__aenter__` / `__aexit__` — no-ops returning `self`.
  - `make_executor(workdir, toolsets, isolation=None) -> Executor` — returns `LocalExecutor` when `isolation` is `None`, `DockerExecutor` otherwise. The `poieo.tools.docker` import happens **inside** the isolation branch, so a machine without Docker never imports it and `poieo run` starts no slower.

**The one runtime change.** In `AgentNode.run`:

```python
executor = LocalExecutor(workdir, spec.tools or DEFAULT_TOOLSETS)
```

becomes

```python
async with make_executor(workdir, spec.tools or DEFAULT_TOOLSETS, isolation) as executor:
    ...
```

and the turn loop moves inside. That is the whole diff the runtime sees: no `if`, no Docker import, no knowledge that a container is a thing. If this task ends with the word "docker" anywhere in `runtime/`, it went wrong.

- [ ] **Step 1: Write the failing tests**

```python
async def test_local_executor_works_as_a_context_manager(tmp_path): ...
async def test_make_executor_returns_local_without_isolation(tmp_path): ...
async def test_make_executor_does_not_import_docker_without_isolation(): ...  # sys.modules
async def test_an_agent_node_still_runs_unchanged(tmp_path): ...              # the no-op proof
```

- [ ] **Step 2: Run the tests to verify they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the full suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio`
Expected: the baseline above, plus the new tests. The pre-existing 8484 failure may or may not appear depending on whether a daemon is running; anything else that turns red is yours.

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor: executors are context managers behind one factory"
```

---

### Task 3: flow-level `isolation`

**Files:**
- Modify: `src/poieo/daemon/config.py`
- Modify: whichever module Plan C used to carry a flow value into `AgentNode.run`
- Test: `tests/test_daemon.py` (append)

**Interfaces:**
- Produces: `IsolationSpec` (`image: str` required, `network: Literal["none","bridge"] = "none"`, `user: str | None = None`, `extra="forbid"`) and `FlowSpec.isolation: IsolationSpec | None = None`.

**Read Plan C's landed diff before writing anything here.** It solved "a flow-level value reaches agent nodes" for `workdir`; this is the same problem with a second value. Extend its route. Two parallel mechanisms for the same job is the failure mode to avoid, and it is easier to avoid now than to unpick later.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_flow_parses_an_isolation_block(): ...
def test_image_is_required_when_the_block_is_present(): ...
def test_network_defaults_to_none(): ...
def test_an_unknown_isolation_key_is_rejected(): ...        # extra="forbid"
def test_a_flow_without_isolation_is_unchanged(): ...
async def test_the_setting_reaches_the_agent_node(): ...    # via Plan C's route
```

- [ ] **Step 2: Run the tests to verify they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: flows opt into isolation, and the setting reaches agent nodes"
```

---

### Task 4: preflight — fail at launch, not at 3am

**Files:**
- Modify: `src/poieo/daemon/config.py` (`load_flows`)
- Modify: `src/poieo/cli.py` (the `check` command)
- Test: `tests/test_daemon.py`, `tests/test_cli.py` (append)

**Interfaces:** none new — `docker_available()` and `image_present()` from Task 1 are called at load time.

Every flow declaring `isolation` is checked when the config loads: docker on PATH, the daemon answering, and the named image present locally. A missing image prints the fix verbatim — `docker pull python:3.12-slim` — because the next thing the user will do is search for that command.

This is the slowest preflight in the codebase (a daemon ping plus an image inspect per distinct image). Cache by image within one load so ten flows sharing an image cost one check. A flow whose image was pruned last week must not discover it at 3am, which is what buys the cost.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_flow_with_isolation_fails_to_load_without_docker(monkeypatch): ...
def test_a_missing_image_names_the_pull_command(monkeypatch): ...
def test_the_same_image_is_only_checked_once(monkeypatch): ...
def test_flows_without_isolation_never_touch_docker(monkeypatch): ...   # no ping at all
def test_check_reports_isolation_readiness(): ...
```

`docker_available` is monkeypatched here, not driven for real — this task tests poieo's reaction to an answer, not Docker itself. Task 1 is where the real thing is exercised.

- [ ] **Step 2: Run the tests to verify they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: isolation is verified when the config loads"
```

---

### Task 5: `poieo run --isolate`

**Files:**
- Modify: `src/poieo/cli.py`
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Produces: `--isolate <image>` on `poieo run`, building an `IsolationSpec` with the defaults from Task 3 and running it through the same preflight.

A one-shot run gets the same box the daemon does, or the feature is something you can only test by writing a daemon config — which means nobody will test it.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_isolate_builds_an_isolation_spec(monkeypatch): ...
def test_run_isolate_preflights_before_the_first_model_call(monkeypatch): ...
def test_run_without_isolate_never_touches_docker(monkeypatch): ...
```

- [ ] **Step 2: Run the tests to verify they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: poieo run --isolate"
```

---

### Task 6: document it and show it working

**Files:**
- Modify: `README.md`
- Modify: `DESIGN.md` (the capability-layer and safety-boundary text only)
- Modify: `examples/poieo.yaml` (one disabled flow, like `nightly-digest`)

**Interfaces:** none — this ships what the previous five built.

- [ ] **Step 1: The example**

Add one flow to `examples/poieo.yaml`, `enabled: false`, with an `isolation` block and a comment saying it needs `docker pull python:3.12-slim` first. Disabled, because an example that fails to load on a machine without Docker would break `poieo check` for everyone.

- [ ] **Step 2: README**

Three or four sentences in the README's plain tone: what opting in changes (`run_command` sees only the workdir), what it does not (file tools were already confined), that the network is off unless asked for, and that the image must exist locally.

- [ ] **Step 3: DESIGN.md**

The safety-boundaries section says container isolation is opt-in; that is now true rather than planned. Change the status, not the argument, and keep the file under 500 lines and at the logic level.

- [ ] **Step 4: The whole suite, both ways**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio
```

Then stop Docker Desktop and run it again. Expected: green both times — the container tests skip with a reason in the second run, and nothing else changes. Paste both summary lines into the report.

- [ ] **Step 5: End-to-end by hand**

Run an isolated agent flow against `examples/graphs/agent-task.yaml` with the mock binding, watch it in the browser, and confirm the tool calls land. Then set the prompt to read something above the workdir and confirm the model gets an error back and keeps working — the model must *see* a tool failure, not have the run die.

- [ ] **Step 6: Commit**

```bash
git commit -m "docs: container isolation, opt-in per task"
```

---

## Done means

- A flow with `isolation` runs shell commands that cannot read one directory above the workdir; the same flow without it can. Both are tests, and they run in CI-less reality on a machine with Docker running.
- `grep -ri docker src/poieo --include=*.py` matches `tools/docker.py`, one lazy import in `tools/__init__.py`, and the preflight call in `daemon/config.py`. Nothing else.
- A machine without Docker runs the full suite green and every existing flow unchanged.
- A flow whose image is missing fails when the config loads, naming the `docker pull` that fixes it.
- Adding Podman later is one new module and one factory branch — no runtime change, no config reshuffle.
