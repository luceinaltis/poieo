# Agent Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `agent` node type whose model can call file/shell tools inside a confined workdir, looping until it answers without a tool call.

**Architecture:** Neutral `ToolDef`/`ToolCall` types extend the provider contract; each backend translates them to its wire format. A `LocalExecutor` owns tool execution and path confinement. `AgentNode` runs the call→execute→feed-back loop bounded by `max_turns`.

**Tech Stack:** Python 3.10+, pydantic v2, httpx, anthropic SDK, pytest (asyncio auto mode). **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-08-21-agent-node-design.md`

## Global Constraints

- No new pip dependencies; stdlib + existing deps only.
- All pydantic models use `ConfigDict(extra="forbid")` (follow `_Spec` in graph.py/binding.py).
- Validation errors surface at graph load (SpecError), never mid-run, wherever possible.
- Tool *failures* (missing file, non-zero exit, timeout, blocked path) return error text to the model; they never fail the node.
- Every task ends with `pytest -q` fully green (run from repo root; conftest.py adds `src/` to sys.path).
- Comment style: sparse, explains constraints, matches existing files.
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

```
src/poieo/tools/__init__.py   NEW  ToolError/ToolResult/Tool, TOOLSETS registry, LocalExecutor
src/poieo/tools/files.py      NEW  read_file / write_file / list_dir / glob_files + path confinement
src/poieo/tools/shell.py      NEW  run_command
src/poieo/providers/base.py   MOD  ToolDef, ToolCall; LLMRequest.tools, LLMResponse.tool_calls
src/poieo/providers/mock.py   MOD  dict script entries may declare tool_calls
src/poieo/providers/local.py  MOD  ollama + openai_compatible tool translation
src/poieo/providers/anthropic_provider.py  MOD  tool_use/tool_result translation
src/poieo/graph.py            MOD  agent node type, workdir/tools/max_turns, roles() fix
src/poieo/runtime/nodes.py    MOD  shared helpers, AgentNode, NODE_TYPES["agent"]
src/poieo/runtime/context.py  MOD  RunContext.cancel field
src/poieo/runtime/executor.py MOD  pass cancel into RunContext
tests/test_tools.py           NEW
tests/test_graph.py           MOD
tests/test_providers.py       MOD
tests/test_runtime.py         MOD
examples/graphs/agent-task.yaml, examples/bindings/mock.yaml, README.md, DESIGN.md  (final task)
```

---

### Task 1: Neutral tool types on the provider contract + mock tool scripting

**Files:**
- Modify: `src/poieo/providers/base.py`
- Modify: `src/poieo/providers/mock.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Produces: `ToolDef(name: str, description: str, input_schema: dict)`, `ToolCall(id: str, name: str, arguments: dict)` (both `@dataclass(slots=True)` in `poieo.providers.base`); `LLMRequest.tools: list[ToolDef]` (default `[]`); `LLMResponse.tool_calls: list[ToolCall]` (default `[]`). Mock script entries may be dicts: `{"text": str, "tool_calls": [{"name": ..., "arguments": {...}}]}`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_providers.py`:

```python
from poieo.providers.base import ToolCall, ToolDef


def test_llm_request_and_response_default_to_no_tools():
    request = LLMRequest(model="m", messages=[])
    response = LLMResponse(text="t", model="m")
    assert request.tools == []
    assert response.tool_calls == []


async def test_mock_scripts_tool_calls():
    spec = ProviderSpec.model_validate(
        {
            "type": "mock",
            "options": {
                "responses": {
                    "worker": [
                        {"tool_calls": [{"name": "read_file", "arguments": {"path": "a.txt"}}]},
                        "done",
                    ]
                }
            },
        }
    )
    provider = MockProvider("fake", spec)
    request = LLMRequest(model="m", messages=[], role="worker")

    first = await provider.complete(request)
    assert first.text == ""
    assert first.tool_calls == [ToolCall(id="mock_1", name="read_file", arguments={"path": "a.txt"})]
    assert first.stop_reason == "tool_use"

    second = await provider.complete(request)
    assert second.text == "done"
    assert second.tool_calls == []
```

(Match the file's existing imports: it already imports `LLMRequest`, `LLMResponse`, `MockProvider`, `ProviderSpec` — add whichever are missing.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_providers.py -q`
Expected: FAIL — `ImportError: cannot import name 'ToolCall'`

- [ ] **Step 3: Implement.** In `src/poieo/providers/base.py`, after `Usage`:

```python
@dataclass(slots=True)
class ToolDef:
    """A tool offered to the model, declared as JSON Schema."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    """One tool invocation the model asked for."""

    id: str
    name: str
    arguments: dict[str, Any]
```

Extend the two dataclasses:

```python
# on LLMRequest, after `role`:
    # Tools offered for this call; empty means a plain completion.
    tools: list[ToolDef] = field(default_factory=list)

# on LLMResponse, after `stop_reason`:
    # Calls the model wants executed; empty means it is done.
    tool_calls: list[ToolCall] = field(default_factory=list)
```

In `src/poieo/providers/mock.py`, replace the tail of `complete` (from `text = value if ...`) with:

```python
        tool_calls: list[ToolCall] = []
        text = ""
        if isinstance(value, dict):
            # A dict entry scripts an assistant turn that may request tools.
            text = value.get("text", "")
            for i, call in enumerate(value.get("tool_calls", []), start=1):
                tool_calls.append(
                    ToolCall(
                        id=f"mock_{len(self.calls)}" if len(value.get("tool_calls", [])) == 1 else f"mock_{len(self.calls)}_{i}",
                        name=call["name"],
                        arguments=dict(call.get("arguments", {})),
                    )
                )
        else:
            text = value if isinstance(value, str) else str(value)
        return LLMResponse(
            text=text,
            model=request.model,
            usage=Usage(input_tokens=0, output_tokens=len(text.split())),
            stop_reason="tool_use" if tool_calls else "end_turn",
            tool_calls=tool_calls,
        )
```

Import `ToolCall` in mock.py's `from .base import ...` line. (With one scripted call and one prior request, the id comes out `mock_1` as the test expects.)

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS (existing string-script behaviour unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/poieo/providers/base.py src/poieo/providers/mock.py tests/test_providers.py
git commit -m "feat: neutral tool types on the provider contract; mock scripts tool calls"
```

---

### Task 2: files toolset with path confinement

**Files:**
- Create: `src/poieo/tools/__init__.py` (types only in this task)
- Create: `src/poieo/tools/files.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces: in `poieo.tools`: `ToolError(PoieoError)`, `ToolResult(text: str, error: bool = False)` (dataclass), `Tool(definition: ToolDef, run: Callable[[Path, dict], Awaitable[str]])` (dataclass). In `poieo.tools.files`: `resolve_path(workdir: Path, raw: str) -> Path` and `FILES_TOOLS: list[Tool]` containing `read_file`, `write_file`, `list_dir`, `glob_files`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_tools.py`:

```python
import pytest

from poieo.tools import ToolError
from poieo.tools.files import FILES_TOOLS, resolve_path

TOOLS = {t.definition.name: t for t in FILES_TOOLS}


def test_resolve_path_blocks_escapes(tmp_path):
    (tmp_path / "inner").mkdir()
    assert resolve_path(tmp_path, "inner/a.txt") == tmp_path / "inner" / "a.txt"
    for raw in ("../outside.txt", "inner/../../outside.txt"):
        with pytest.raises(ToolError):
            resolve_path(tmp_path, raw)


def test_resolve_path_blocks_absolute_paths_outside(tmp_path):
    with pytest.raises(ToolError):
        resolve_path(tmp_path, str(tmp_path.parent / "elsewhere.txt"))
    # An absolute path *inside* the workdir is fine.
    assert resolve_path(tmp_path, str(tmp_path / "ok.txt")) == tmp_path / "ok.txt"


async def test_read_write_roundtrip(tmp_path):
    await TOOLS["write_file"].run(tmp_path, {"path": "notes/a.txt", "content": "hello"})
    text = await TOOLS["read_file"].run(tmp_path, {"path": "notes/a.txt"})
    assert "hello" in text


async def test_read_missing_file_raises_tool_error(tmp_path):
    with pytest.raises(ToolError, match="a.txt"):
        await TOOLS["read_file"].run(tmp_path, {"path": "a.txt"})


async def test_read_truncates_large_files(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 250_000)
    text = await TOOLS["read_file"].run(tmp_path, {"path": "big.txt"})
    assert len(text) < 210_000
    assert "truncated" in text


async def test_list_dir_and_glob(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text("x = 1")
    (tmp_path / "top.txt").write_text("t")
    listing = await TOOLS["list_dir"].run(tmp_path, {})
    assert "pkg" in listing and "top.txt" in listing
    found = await TOOLS["glob_files"].run(tmp_path, {"pattern": "**/*.py"})
    assert "pkg/m.py" in found.replace("\\", "/")


async def test_glob_rejects_escaping_pattern(tmp_path):
    with pytest.raises(ToolError):
        await TOOLS["glob_files"].run(tmp_path, {"pattern": "../**/*.py"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'poieo.tools'`

- [ ] **Step 3: Implement.** Create `src/poieo/tools/__init__.py`:

```python
"""Tools an agent node may hand to its model, and the executor that runs them.

A node never touches the filesystem or a subprocess directly: it hands the
model's :class:`~poieo.providers.base.ToolCall`s to an executor and gets text
back. Tool *failures* become error text for the model to read and correct --
only harness bugs raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..errors import PoieoError
from ..providers.base import ToolDef


class ToolError(PoieoError):
    """An expected tool failure, reported back to the model as text."""


@dataclass(slots=True)
class ToolResult:
    text: str
    error: bool = False


@dataclass(slots=True)
class Tool:
    """A declaration plus the coroutine that executes it inside a workdir."""

    definition: ToolDef
    run: Callable[[Path, dict[str, Any]], Awaitable[str]]
```

Create `src/poieo/tools/files.py`:

```python
"""File tools, confined to the working directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..providers.base import ToolDef
from . import Tool, ToolError

_READ_CAP = 200_000     # characters
_GLOB_CAP = 500         # paths


def resolve_path(workdir: Path, raw: str) -> Path:
    """Resolve ``raw`` against ``workdir`` and refuse anything that escapes.

    ``resolve()`` follows symlinks, so a link pointing outside is caught too.
    """
    root = workdir.resolve()
    raw_path = Path(raw)
    candidate = (raw_path if raw_path.is_absolute() else root / raw_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ToolError(f"path '{raw}' escapes the working directory")
    return candidate


async def _read_file(workdir: Path, args: dict[str, Any]) -> str:
    path = resolve_path(workdir, args["path"])
    if not path.is_file():
        raise ToolError(f"no such file: {args['path']}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > _READ_CAP:
        return text[:_READ_CAP] + f"\n... [truncated: file is {len(text)} characters]"
    return text


async def _write_file(workdir: Path, args: dict[str, Any]) -> str:
    path = resolve_path(workdir, args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = str(args.get("content", ""))
    path.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {args['path']}"


async def _list_dir(workdir: Path, args: dict[str, Any]) -> str:
    path = resolve_path(workdir, args.get("path", "."))
    if not path.is_dir():
        raise ToolError(f"no such directory: {args.get('path', '.')}")
    lines = []
    for entry in sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name)):
        if entry.is_dir():
            lines.append(f"{entry.name}/")
        else:
            lines.append(f"{entry.name}  ({entry.stat().st_size} bytes)")
    return "\n".join(lines) or "(empty)"


async def _glob_files(workdir: Path, args: dict[str, Any]) -> str:
    pattern = args["pattern"]
    if ".." in pattern.split("/") or ".." in pattern.split("\\"):
        raise ToolError("glob patterns may not contain '..'")
    matches = sorted(
        p.relative_to(workdir).as_posix()
        for p in workdir.glob(pattern)
        if p.is_file()
    )
    if len(matches) > _GLOB_CAP:
        return "\n".join(matches[:_GLOB_CAP]) + f"\n... [{len(matches) - _GLOB_CAP} more]"
    return "\n".join(matches) or "(no matches)"


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


FILES_TOOLS: list[Tool] = [
    Tool(
        ToolDef(
            name="read_file",
            description="Read a text file. Paths are relative to the working directory.",
            input_schema=_schema({"path": {"type": "string"}}, ["path"]),
        ),
        _read_file,
    ),
    Tool(
        ToolDef(
            name="write_file",
            description="Write a text file, creating parent directories as needed.",
            input_schema=_schema(
                {"path": {"type": "string"}, "content": {"type": "string"}}, ["path"]
            ),
        ),
        _write_file,
    ),
    Tool(
        ToolDef(
            name="list_dir",
            description="List a directory. Omit path for the working directory itself.",
            input_schema=_schema({"path": {"type": "string"}}, []),
        ),
        _list_dir,
    ),
    Tool(
        ToolDef(
            name="glob_files",
            description="Find files by glob pattern, e.g. '**/*.py'.",
            input_schema=_schema({"pattern": {"type": "string"}}, ["pattern"]),
        ),
        _glob_files,
    ),
]
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/poieo/tools tests/test_tools.py
git commit -m "feat: files toolset confined to the workdir"
```

---

### Task 3: shell toolset

**Files:**
- Create: `src/poieo/tools/shell.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces: `poieo.tools.shell.SHELL_TOOLS: list[Tool]` containing `run_command(command, timeout?)`. Output format: first line `exit code: N`, then combined stdout+stderr (20KB cap).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_tools.py`:

```python
from poieo.tools.shell import SHELL_TOOLS

SHELL = {t.definition.name: t for t in SHELL_TOOLS}


async def test_run_command_reports_exit_code_and_output(tmp_path):
    out = await SHELL["run_command"].run(tmp_path, {"command": "echo hello"})
    assert out.startswith("exit code: 0")
    assert "hello" in out


async def test_run_command_nonzero_exit_is_reported_not_raised(tmp_path):
    out = await SHELL["run_command"].run(tmp_path, {"command": "exit 3"})
    assert out.startswith("exit code: 3")


async def test_run_command_runs_in_workdir(tmp_path):
    (tmp_path / "here.txt").write_text("x")
    out = await SHELL["run_command"].run(tmp_path, {"command": "dir /b" if __import__("os").name == "nt" else "ls"})
    assert "here.txt" in out


async def test_run_command_times_out(tmp_path):
    import os
    sleeper = "ping -n 30 127.0.0.1 > NUL" if os.name == "nt" else "sleep 30"
    with pytest.raises(ToolError, match="timed out"):
        await SHELL["run_command"].run(tmp_path, {"command": sleeper, "timeout": 1})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'poieo.tools.shell'`

- [ ] **Step 3: Implement.** Create `src/poieo/tools/shell.py`:

```python
"""Shell tool. The command's cwd is pinned to the workdir; the command itself
can still name absolute paths -- that boundary needs an OS sandbox, which the
local executor does not claim to be (see the design spec)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..providers.base import ToolDef
from . import Tool, ToolError

_DEFAULT_TIMEOUT = 120.0
_MAX_TIMEOUT = 600.0
_OUTPUT_CAP = 20_000


async def _run_command(workdir: Path, args: dict[str, Any]) -> str:
    command = str(args["command"])
    timeout = min(float(args.get("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=workdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise ToolError(f"command timed out after {timeout:.0f}s: {command}")
    text = stdout.decode(errors="replace")
    if len(text) > _OUTPUT_CAP:
        text = text[:_OUTPUT_CAP] + "\n... [output truncated]"
    return f"exit code: {process.returncode}\n{text}"


SHELL_TOOLS: list[Tool] = [
    Tool(
        ToolDef(
            name="run_command",
            description=(
                "Run a shell command in the working directory. Returns the exit "
                "code and combined stdout/stderr."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "number", "description": "seconds, max 600"},
                },
                "required": ["command"],
            },
        ),
        _run_command,
    ),
]
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/poieo/tools/shell.py tests/test_tools.py
git commit -m "feat: shell toolset with timeout and output cap"
```

---

### Task 4: toolset registry + LocalExecutor

**Files:**
- Modify: `src/poieo/tools/__init__.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces: `TOOLSETS: dict[str, list[Tool]]` (`{"files": FILES_TOOLS, "shell": SHELL_TOOLS}`), `DEFAULT_TOOLSETS = ["files", "shell"]`, and `LocalExecutor(workdir: Path, toolsets: Sequence[str])` with `.definitions() -> list[ToolDef]` and `async .execute(call: ToolCall) -> ToolResult`. Unknown tool names and all `ToolError`s/unexpected exceptions come back as `ToolResult(error=True)`, never raised.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_tools.py`:

```python
from poieo.providers.base import ToolCall
from poieo.tools import DEFAULT_TOOLSETS, TOOLSETS, LocalExecutor


def test_registry_names():
    assert set(TOOLSETS) == {"files", "shell"}
    assert DEFAULT_TOOLSETS == ["files", "shell"]


def test_executor_declares_selected_toolsets(tmp_path):
    only_files = LocalExecutor(tmp_path, ["files"])
    names = {d.name for d in only_files.definitions()}
    assert "read_file" in names and "run_command" not in names


async def test_executor_runs_a_call(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    ex = LocalExecutor(tmp_path, DEFAULT_TOOLSETS)
    result = await ex.execute(ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}))
    assert not result.error
    assert result.text == "data"


async def test_executor_turns_failures_into_error_results(tmp_path):
    ex = LocalExecutor(tmp_path, DEFAULT_TOOLSETS)
    missing = await ex.execute(ToolCall(id="1", name="read_file", arguments={"path": "nope"}))
    assert missing.error and "nope" in missing.text
    unknown = await ex.execute(ToolCall(id="2", name="fly", arguments={}))
    assert unknown.error and "fly" in unknown.text
    bad_args = await ex.execute(ToolCall(id="3", name="read_file", arguments={}))
    assert bad_args.error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools.py -q`
Expected: FAIL — `ImportError: cannot import name 'LocalExecutor'`

- [ ] **Step 3: Implement.** Append to `src/poieo/tools/__init__.py` (imports of the toolset modules must sit *below* the `Tool`/`ToolError` definitions they depend on):

```python
from ..providers.base import ToolCall  # noqa: E402  (with the other imports at top)


class LocalExecutor:
    """Runs tool calls directly on this machine, confined to one workdir.

    The executor is the seam a future container-backed implementation slots
    into: same definitions(), same execute(), different blast radius.
    """

    def __init__(self, workdir: Path, toolsets: "Sequence[str]"):
        self.workdir = workdir
        self.tools: dict[str, Tool] = {}
        for name in toolsets:
            for tool in TOOLSETS[name]:
                self.tools[tool.definition.name] = tool

    def definitions(self) -> list[ToolDef]:
        return [tool.definition for tool in self.tools.values()]

    async def execute(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(f"unknown tool '{call.name}'", error=True)
        try:
            return ToolResult(await tool.run(self.workdir, call.arguments))
        except ToolError as exc:
            return ToolResult(str(exc), error=True)
        except Exception as exc:  # a bad argument shape must not kill the run
            return ToolResult(f"{type(exc).__name__}: {exc}", error=True)


from .files import FILES_TOOLS  # noqa: E402
from .shell import SHELL_TOOLS  # noqa: E402

TOOLSETS: dict[str, list[Tool]] = {"files": FILES_TOOLS, "shell": SHELL_TOOLS}
DEFAULT_TOOLSETS: list[str] = ["files", "shell"]
```

Add `Sequence` to the `typing` import at the top. Note the bottom imports are deliberate: `files.py`/`shell.py` import `Tool` from this package, so they load after it is defined (same pattern as pydantic's late rebuild — a short comment in the file should say why).

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/poieo/tools/__init__.py tests/test_tools.py
git commit -m "feat: toolset registry and LocalExecutor"
```

---

### Task 5: graph schema — the agent node type

**Files:**
- Modify: `src/poieo/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces: `NodeSpec.type` accepts `"agent"`; new fields `workdir: str | None`, `tools: list[str] | None` (None = all toolsets), `max_turns: int` (default 20, 1–200). `GraphSpec.roles()` includes agent nodes. Validation: agent requires `prompt` + `workdir`, rejects `branches`; unknown toolset names rejected; `workdir` template validated; llm/router nodes reject `workdir`/`tools`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_graph.py` (follow that file's existing helper style; if it has a `node()`/`graph()` helper, reuse it, otherwise use `GraphSpec.model_validate` directly as below):

```python
def _agent_graph(**overrides):
    node = {
        "id": "work",
        "type": "agent",
        "role": "worker",
        "workdir": "/tmp/proj",
        "prompt": "do the thing",
    }
    node.update(overrides)
    return {"name": "g", "entry": "work", "nodes": [node]}


def test_agent_node_parses_with_defaults():
    graph = GraphSpec.model_validate(_agent_graph())
    node = graph.node("work")
    assert node.max_turns == 20
    assert node.tools is None  # None means every toolset


def test_agent_node_requires_workdir():
    with pytest.raises(ValidationError, match="workdir"):
        GraphSpec.model_validate(_agent_graph(workdir=None))


def test_agent_node_rejects_unknown_toolset():
    with pytest.raises(ValidationError, match="parachute"):
        GraphSpec.model_validate(_agent_graph(tools=["parachute"]))


def test_agent_node_rejects_branches():
    with pytest.raises(ValidationError, match="branches"):
        GraphSpec.model_validate(_agent_graph(branches=[{"when": "True", "to": None}]))


def test_llm_node_rejects_agent_only_fields():
    spec = {
        "name": "g",
        "entry": "a",
        "nodes": [{"id": "a", "type": "llm", "prompt": "p", "workdir": "/x"}],
    }
    with pytest.raises(ValidationError, match="workdir"):
        GraphSpec.model_validate(spec)


def test_roles_includes_agent_nodes():
    graph = GraphSpec.model_validate(_agent_graph())
    assert graph.roles() == {"worker"}
```

(`ValidationError` comes from pydantic; check the file's imports — it may already catch `SpecError` wrappers instead. If the file asserts on `SpecError`, wrap with `pytest.raises(Exception, match=...)` is NOT acceptable — import `from pydantic import ValidationError`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_graph.py -q`
Expected: FAIL — the `type` Literal rejects `"agent"`

- [ ] **Step 3: Implement in `src/poieo/graph.py`:**

`NodeSpec.type` becomes `Literal["llm", "router", "agent"]`. Add fields after `params`:

```python
    # --- agent nodes ---
    # Every tool call is confined to this directory. Templates allowed.
    workdir: str | None = None
    # Toolset names from poieo.tools.TOOLSETS; None means all of them.
    tools: list[str] | None = None
    # Upper bound on model calls in one node execution.
    max_turns: int = Field(default=20, ge=1, le=200)
```

Rework `_check_shape` — replace the current if/else with three arms:

```python
    @model_validator(mode="after")
    def _check_shape(self) -> NodeSpec:
        if self.type in ("llm", "agent"):
            if not self.prompt:
                raise ValueError(f"{self.type} node '{self.id}' requires a prompt")
            if self.branches:
                raise ValueError(f"{self.type} node '{self.id}' cannot declare branches")
            try:
                validate_template(self.prompt)
                if self.system:
                    validate_template(self.system)
            except ExpressionError as exc:
                raise ValueError(f"node '{self.id}': {exc}") from exc
        if self.type == "agent":
            if not self.workdir:
                raise ValueError(f"agent node '{self.id}' requires a workdir")
            try:
                validate_template(self.workdir)
            except ExpressionError as exc:
                raise ValueError(f"node '{self.id}': {exc}") from exc
            from .tools import TOOLSETS  # late import; tools pulls in providers

            for name in self.tools or []:
                if name not in TOOLSETS:
                    raise ValueError(
                        f"agent node '{self.id}' names unknown toolset '{name}'; "
                        f"known: {sorted(TOOLSETS)}"
                    )
        else:
            if self.workdir or self.tools:
                raise ValueError(
                    f"{self.type} node '{self.id}' does not take workdir/tools"
                )
        if self.type == "router":
            if not self.branches:
                raise ValueError(f"router node '{self.id}' requires at least one branch")
            if self.prompt or self.role:
                raise ValueError(
                    f"router node '{self.id}' does not call a model; drop prompt/role"
                )
            if self.next:
                raise ValueError(
                    f"router node '{self.id}' routes via branches/default, not next"
                )
        return self
```

Fix `roles()`:

```python
    def roles(self) -> set[str]:
        """Every logical role this graph needs a binding for."""
        return {
            n.role or self.default_role
            for n in self.nodes
            if n.type in ("llm", "agent")
        }
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/poieo/graph.py tests/test_graph.py
git commit -m "feat: agent node type in the graph schema"
```

---

### Task 6: extract shared node helpers (pure refactor)

**Files:**
- Modify: `src/poieo/runtime/nodes.py`

**Interfaces:**
- Produces: module-level `async def call_with_retry(spec: NodeSpec, provider, request: LLMRequest, ctx: RunContext) -> LLMResponse` and `def shape_output(spec: NodeSpec, text: str) -> Any` in `runtime/nodes.py`. `LLMNode` delegates to both. No behaviour change.

- [ ] **Step 1: Move the bodies.** `LLMNode._call_with_retry` becomes module function `call_with_retry(spec, provider, request, ctx)` (replace `self.spec` with `spec`); `LLMNode._shape_output` becomes `shape_output(spec, text)` (replace `self.spec` with `spec`). `LLMNode.run` calls `call_with_retry(self.spec, provider, request, ctx)` and `shape_output(self.spec, response.text)`. Delete the methods.

- [ ] **Step 2: Run the full suite — this is the whole safety net for a refactor**

Run: `pytest -q`
Expected: PASS, identical count to before

- [ ] **Step 3: Commit**

```bash
git add src/poieo/runtime/nodes.py
git commit -m "refactor: extract call_with_retry and shape_output for reuse"
```

---

### Task 7: AgentNode — the tool loop

**Files:**
- Modify: `src/poieo/runtime/nodes.py`, `src/poieo/runtime/context.py`, `src/poieo/runtime/executor.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Consumes: `LocalExecutor`, `DEFAULT_TOOLSETS` (Task 4); `ToolDef`/`ToolCall` on requests/responses (Task 1); `call_with_retry`/`shape_output` (Task 6); agent NodeSpec fields (Task 5).
- Produces: `AgentNode` registered as `NODE_TYPES["agent"]`; `RunContext.cancel: asyncio.Event | None = None` (set by `execute()`); `node_tool_call` events with `{turn, name, arguments, result, error, duration_ms}`. Neutral history grows as: assistant turn `{"role": "assistant", "content": text, "tool_calls": [{"id", "name", "arguments"}]}`, tool turn `{"role": "tool", "tool_call_id": id, "content": text}`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_runtime.py`:

```python
def agent_graph(workdir, **node_overrides):
    node = {
        "id": "work",
        "type": "agent",
        "role": "worker",
        "workdir": str(workdir),
        "prompt": "do it",
        "output": {"as": "report"},
    }
    node.update(node_overrides)
    return GraphSpec.model_validate({"name": "ag", "entry": "work", "nodes": [node]})


async def test_agent_node_runs_tools_and_finishes(tmp_path):
    (tmp_path / "notes.txt").write_text("secret-content")
    graph = agent_graph(tmp_path)
    binding = mock_binding(
        {
            "worker": [
                {"tool_calls": [{"name": "read_file", "arguments": {"path": "notes.txt"}}]},
                "done",
            ]
        }
    )
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    assert result.outputs["work"] == "done"
    # The second model call must carry the tool result back.
    second_call = provider.calls[1]
    tool_turns = [m for m in second_call.messages if m["role"] == "tool"]
    assert tool_turns and "secret-content" in tool_turns[0]["content"]
    assert second_call.messages[-2]["role"] == "assistant"


async def test_agent_node_survives_tool_errors(tmp_path):
    graph = agent_graph(tmp_path)
    binding = mock_binding(
        {
            "worker": [
                {"tool_calls": [{"name": "read_file", "arguments": {"path": "missing"}}]},
                "recovered",
            ]
        }
    )
    result = await run_graph(graph, binding)
    assert result.status == "completed"
    assert result.outputs["work"] == "recovered"


async def test_agent_node_stops_at_max_turns(tmp_path):
    graph = agent_graph(tmp_path, max_turns=3)
    # The script's last entry repeats forever, so the model never finishes.
    binding = mock_binding(
        {"worker": [{"tool_calls": [{"name": "list_dir", "arguments": {}}]}]}
    )
    result = await run_graph(graph, binding)
    assert result.status == "failed"
    assert "max_turns" in result.error


async def test_agent_node_fails_cleanly_on_missing_workdir(tmp_path):
    graph = agent_graph(tmp_path / "not-there")
    binding = mock_binding({"worker": "hi"})
    result = await run_graph(graph, binding)
    assert result.status == "failed"
    assert "workdir" in result.error
```

Reuse the file's existing `mock_binding` and `run_graph` helpers; import `NullStore`, `execute`, `ProviderPool`, `GraphSpec` are already imported there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runtime.py -q`
Expected: FAIL — `NODE_TYPES` has no `"agent"` (build_node raises NodeError → run status "failed" with unknown-type message, so assertions on outputs fail)

- [ ] **Step 3: Implement.**

`src/poieo/runtime/context.py` — add to `RunContext` after `iteration`:

```python
    # Set by execute(); agent loops poll it between turns.
    cancel: asyncio.Event | None = None
```

(add `import asyncio` at the top.)

`src/poieo/runtime/executor.py` — pass it in when building the context: add `cancel=cancel,` to the `RunContext(...)` construction.

`src/poieo/runtime/nodes.py` — add after `LLMNode`:

```python
def _clip(value: Any, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


class AgentNode(Node):
    """Hands the model tools and loops until it answers without one.

    "Keeps working" belongs to the graph and the daemon; this loop is only
    the mechanics of one step doing its job, bounded by max_turns.
    """

    async def run(self, ctx: RunContext) -> NodeResult:
        spec = self.spec
        role = spec.role or ctx.graph.default_role
        resolved = ctx.binding.resolve(role, spec.params or None)
        provider = ctx.pool.get(resolved.provider_name)

        scope = ctx.scope()
        try:
            prompt = render(spec.prompt or "", scope)
            system = render(spec.system, scope) if spec.system else None
            workdir = Path(render(spec.workdir or "", scope)).expanduser()
        except ExpressionError as exc:
            raise NodeError(f"node '{spec.id}': {exc}", node_id=spec.id) from exc
        if not workdir.is_dir():
            raise NodeError(
                f"node '{spec.id}': workdir does not exist: {workdir}", node_id=spec.id
            )

        executor = LocalExecutor(workdir, spec.tools or DEFAULT_TOOLSETS)
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        turns = 0
        tool_call_count = 0

        while True:
            if ctx.cancel is not None and ctx.cancel.is_set():
                raise RunAborted(f"cancelled during agent node '{spec.id}'")
            turns += 1
            request = LLMRequest(
                model=resolved.model,
                messages=list(messages),
                system=system,
                params=dict(resolved.params),
                role=role,
                tools=executor.definitions(),
            )
            response = await call_with_retry(spec, provider, request, ctx)
            ctx.usage = ctx.usage.merge(response.usage)

            if not response.tool_calls:
                break
            if turns >= spec.max_turns:
                raise NodeError(
                    f"node '{spec.id}' hit max_turns ({spec.max_turns}) "
                    f"with tool calls still pending",
                    node_id=spec.id,
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": response.text,
                    "tool_calls": [
                        {"id": c.id, "name": c.name, "arguments": c.arguments}
                        for c in response.tool_calls
                    ],
                }
            )
            for call in response.tool_calls:
                started = time.monotonic()
                result = await executor.execute(call)
                tool_call_count += 1
                ctx.emit(
                    "node_tool_call",
                    node_id=spec.id,
                    turn=turns,
                    name=call.name,
                    arguments=_clip(call.arguments),
                    result=_clip(result.text),
                    error=result.error,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result.text}
                )

        output = shape_output(spec, response.text)
        ctx.record_output(spec.id, output, spec.output.as_)
        if spec.output.into_state:
            ctx.state[spec.output.into_state] = unwrap(output)

        return NodeResult(
            node_id=spec.id,
            next_node=spec.next,
            output=output,
            meta={
                "role": role,
                "binding": resolved.describe(),
                "model": response.model,
                "usage": response.usage.as_dict(),
                "stop_reason": response.stop_reason,
                "turns": turns,
                "tool_calls": tool_call_count,
            },
        )
```

New imports in nodes.py: `time`, `Path` (from pathlib), `RunAborted` (from ..errors), `LocalExecutor, DEFAULT_TOOLSETS` (from ..tools), `LLMRequest` already imported. Register:

```python
NODE_TYPES: dict[str, type[Node]] = {
    "llm": LLMNode,
    "router": RouterNode,
    "agent": AgentNode,
}
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/poieo/runtime tests/test_runtime.py
git commit -m "feat: agent node runs the tool loop"
```

---

### Task 8: tool translation for ollama and openai_compatible

**Files:**
- Modify: `src/poieo/providers/local.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: neutral history format from Task 7; `ToolDef`/`ToolCall` from Task 1.
- Produces: module functions in `local.py`: `_wire_tools(tools: list[ToolDef]) -> list[dict]` (shared OpenAI-style wrapper), `_openai_messages(request) -> list[dict]`, `_ollama_messages(request) -> list[dict]`. Both providers send `tools` and parse `tool_calls` from responses.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_providers.py`:

```python
from poieo.providers.local import _ollama_messages, _openai_messages, _wire_tools

NEUTRAL_HISTORY = [
    {"role": "user", "content": "go"},
    {
        "role": "assistant",
        "content": "checking",
        "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}],
    },
    {"role": "tool", "tool_call_id": "c1", "content": "data"},
]

A_TOOL = ToolDef(name="read_file", description="read", input_schema={"type": "object"})


def test_wire_tools_wraps_openai_style():
    assert _wire_tools([A_TOOL]) == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "read",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_openai_messages_translation():
    request = LLMRequest(model="m", messages=NEUTRAL_HISTORY, system="sys")
    messages = _openai_messages(request)
    assert messages[0] == {"role": "system", "content": "sys"}
    assistant = messages[2]
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
    import json
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "a"}
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": "data"}


def test_ollama_messages_translation():
    request = LLMRequest(model="m", messages=NEUTRAL_HISTORY, system=None)
    messages = _ollama_messages(request)
    assistant = messages[1]
    # Ollama takes arguments as a dict, not a JSON string.
    assert assistant["tool_calls"][0]["function"]["arguments"] == {"path": "a"}
    assert messages[2]["role"] == "tool"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_providers.py -q`
Expected: FAIL — `ImportError: cannot import name '_wire_tools'`

- [ ] **Step 3: Implement in `src/poieo/providers/local.py`:**

```python
import json
import uuid

from .base import LLMRequest, LLMResponse, Provider, ToolCall, ToolDef, Usage


def _wire_tools(tools: list[ToolDef]) -> list[dict[str, Any]]:
    """Both local APIs take the OpenAI-style function wrapper."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _translate_history(request: LLMRequest, arguments_as_json: bool) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    for message in request.messages:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                arguments = call["arguments"]
                calls.append(
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(arguments)
                            if arguments_as_json
                            else arguments,
                        },
                    }
                )
            messages.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
        else:
            messages.append(dict(message))
    return messages


def _openai_messages(request: LLMRequest) -> list[dict[str, Any]]:
    return _translate_history(request, arguments_as_json=True)


def _ollama_messages(request: LLMRequest) -> list[dict[str, Any]]:
    return _translate_history(request, arguments_as_json=False)
```

Delete `_with_system` and switch both `complete` methods to the new functions:

- `OpenAICompatibleProvider.complete`: `payload["messages"] = _openai_messages(request)`; after building payload add:

```python
        if request.tools:
            payload["tools"] = _wire_tools(request.tools)
```

and parse calls out of the response after `message = choices[0].get("message") or {}`:

```python
        tool_calls = [
            ToolCall(
                id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=call["function"]["name"],
                arguments=json.loads(call["function"].get("arguments") or "{}"),
            )
            for call in (message.get("tool_calls") or [])
        ]
```

and pass `tool_calls=tool_calls` to the returned `LLMResponse`.

- `OllamaProvider.complete`: `payload["messages"] = _ollama_messages(request)`; same `tools` addition with `_wire_tools`; parse from `message.get("tool_calls")` where `function.arguments` is already a dict:

```python
        tool_calls = [
            ToolCall(
                id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=call["function"]["name"],
                arguments=dict(call["function"].get("arguments") or {}),
            )
            for call in (message.get("tool_calls") or [])
        ]
```

pass `tool_calls=tool_calls` to `LLMResponse`.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/poieo/providers/local.py tests/test_providers.py
git commit -m "feat: tool calling for ollama and openai_compatible providers"
```

---

### Task 9: tool translation for anthropic

**Files:**
- Modify: `src/poieo/providers/anthropic_provider.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: neutral history format; `ToolDef`/`ToolCall`.
- Produces: module functions `_anthropic_tools(tools: list[ToolDef]) -> list[dict]` and `_anthropic_messages(messages: list[dict]) -> list[dict]` (consecutive tool turns merge into ONE user message of `tool_result` blocks — the API requires it). `complete()` extracts `tool_use` blocks into `tool_calls`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_providers.py`:

```python
from poieo.providers.anthropic_provider import _anthropic_messages, _anthropic_tools


def test_anthropic_tools_shape():
    assert _anthropic_tools([A_TOOL]) == [
        {"name": "read_file", "description": "read", "input_schema": {"type": "object"}}
    ]


def test_anthropic_messages_translation_merges_tool_results():
    history = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [
                {"id": "c1", "name": "read_file", "arguments": {"path": "a"}},
                {"id": "c2", "name": "list_dir", "arguments": {}},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "data-1"},
        {"role": "tool", "tool_call_id": "c2", "content": "data-2"},
    ]
    messages = _anthropic_messages(history)
    assert messages[0] == {"role": "user", "content": "go"}
    assistant = messages[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "text", "text": "checking"}
    assert assistant["content"][1] == {
        "type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a"}
    }
    # Both tool results land in ONE user turn.
    results = messages[2]
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["c1", "c2"]
    assert results["content"][0]["type"] == "tool_result"
    assert len(messages) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_providers.py -q`
Expected: FAIL — `ImportError: cannot import name '_anthropic_tools'`

- [ ] **Step 3: Implement in `src/poieo/providers/anthropic_provider.py`:**

```python
def _anthropic_tools(tools: list[ToolDef]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Neutral history -> Anthropic content blocks.

    Consecutive tool turns collapse into one user message: the API expects
    every tool_result for a turn's tool_use blocks together.
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            content: list[dict[str, Any]] = []
            if message.get("content"):
                content.append({"type": "text", "text": message["content"]})
            for call in message["tool_calls"]:
                content.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["name"],
                        "input": call["arguments"],
                    }
                )
            out.append({"role": "assistant", "content": content})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message["tool_call_id"],
                "content": message["content"],
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append(dict(message))
    return out
```

Import `ToolCall, ToolDef` in the `from .base import ...` line. In `_build_kwargs`, replace `"messages": request.messages` with `"messages": _anthropic_messages(request.messages)` and add before the thinking block:

```python
        if request.tools:
            kwargs["tools"] = _anthropic_tools(request.tools)
```

In `complete()`, after extracting `text`, add:

```python
        tool_calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in message.content
            if b.type == "tool_use"
        ]
```

and pass `tool_calls=tool_calls` to the returned `LLMResponse`.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/poieo/providers/anthropic_provider.py tests/test_providers.py
git commit -m "feat: tool calling for the anthropic provider"
```

---

### Task 10: end-to-end example, docs, status

**Files:**
- Create: `examples/graphs/agent-task.yaml`
- Modify: `examples/bindings/mock.yaml`, `README.md`, `DESIGN.md`
- Test: `tests/test_runtime.py`

**Interfaces:** none new — this task proves the whole feature through the public surface and documents it.

- [ ] **Step 1: Write the failing end-to-end test** — append to `tests/test_runtime.py`:

```python
async def test_agent_example_graph_runs_on_the_mock_binding(tmp_path):
    graph = load_graph(EXAMPLES / "graphs/agent-task.yaml")
    binding = load_binding(EXAMPLES / "bindings/mock.yaml")
    result = await run_graph(graph, binding, input={"workdir": str(tmp_path)})
    assert result.status == "completed"
    assert (tmp_path / "TODO.md").exists()
```

Run: `pytest tests/test_runtime.py -q` — Expected: FAIL (file not found).

- [ ] **Step 2: Create `examples/graphs/agent-task.yaml`:**

```yaml
name: agent-task
description: One resident step that actually touches files.
entry: work

nodes:
  - id: work
    type: agent
    role: worker
    workdir: "{{ input.workdir }}"
    prompt: |
      Look at the project in your working directory and write a TODO.md
      listing the three most useful next steps.
    max_turns: 10
    output: {as: report}
```

- [ ] **Step 3: Extend `examples/bindings/mock.yaml`** — add a `worker` script to its `responses` (keep everything already there; match the file's existing structure, adding under the mock provider's `options.responses`):

```yaml
      worker:
        - tool_calls:
            - {name: list_dir, arguments: {}}
        - tool_calls:
            - name: write_file
              arguments: {path: TODO.md, content: "- write more tests\n- add docs\n- ship\n"}
        - "Wrote TODO.md with three next steps."
```

Run: `pytest -q` — Expected: PASS.

- [ ] **Step 4: Document.**

README.md — in the node-types table add a row; after the table add a short subsection:

```markdown
| `agent` | hands the model tools and loops until it finishes one step | `role`, `workdir`, `tools`, `max_turns`, plus the `llm` keys |
```

```markdown
### Agent nodes

An `agent` node gives its model hands: `files` (read/write/list/glob) and
`shell` (run a command) toolsets, every call confined to the node's `workdir`.
The node loops — model asks, poieo executes, result goes back — until the
model answers without a tool call; `max_turns` bounds the loop. Tool failures
are fed back to the model as text so it can correct itself. Every call is
recorded as a `node_tool_call` event in the run log.

Path confinement prevents accidents, not malice: a shell command can still
name absolute paths. Point `workdir` only at a directory you would let a
junior contributor loose in. `poieo run examples/graphs/agent-task.yaml -b
examples/bindings/mock.yaml --set workdir=/tmp/demo` exercises the loop
offline.
```

Also update the "Not built yet" list: remove "tool calls, code execution" from the missing node types line.

DESIGN.md — flip the Hands layer status from `spec approved, next to build` to `done`.

- [ ] **Step 5: Full suite + commit**

Run: `pytest -q` — Expected: PASS.

```bash
git add examples README.md DESIGN.md tests/test_runtime.py
git commit -m "feat: agent example graph, docs, and design status"
```

---

## Self-Review Notes

- Spec coverage: neutral types (T1), mock scripting (T1), files/shell/confinement (T2–3), executor seam (T4), schema+roles (T5), loop+events+cancel+usage (T7), all four provider translations (T1, T8, T9), README security note (T10). Cancellation is polled between turns via `RunContext.cancel` (T7), satisfying the spec's "checked each loop turn".
- The spec's "finish the in-flight tool call, then abort" falls out naturally: the cancel check sits at the top of the turn loop, never between tool executions.
- Type consistency: `ToolCall(id, name, arguments)` used identically in T1 mock, T7 history dicts, T8/T9 translations. `call_with_retry(spec, provider, request, ctx)` defined in T6, consumed in T7.
