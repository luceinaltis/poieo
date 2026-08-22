"""Tools an agent node may hand to its model, and the executor that runs them.

A node never touches the filesystem or a subprocess directly: it hands the
model's :class:`~poieo.providers.base.ToolCall`s to an executor and gets text
back. Tool *failures* become error text for the model to read and correct --
only harness bugs raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict

from ..errors import PoieoError
from ..providers.base import ToolCall, ToolDef


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


class Isolation(BaseModel):
    """Where a task's shell commands may run.

    Deliberately backend-neutral and free of Docker words: a task's
    ``isolation:`` block parses into this, and everything downstream -- the
    factory, the box, the executor -- sees only this shape.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str
    network: Literal["none", "bridge"] = "none"
    user: str | None = None


class Executor:
    """Tool lookup, failure-to-text, and a lifecycle that costs nothing by default.

    Subclasses differ in *where* the tools run, never in what a caller does
    with them: ``async with``, then ``definitions()`` and ``execute()``.
    """

    workdir: Path
    tools: dict[str, Tool]

    def _load(self, toolsets: "Sequence[str]") -> None:
        self.tools = {}
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

    async def __aenter__(self) -> "Executor":
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        return None


class LocalExecutor(Executor):
    """Runs tool calls directly on this machine, confined to one workdir.

    The default, and the one with nothing to set up or tear down -- its
    lifecycle is inherited and does nothing.
    """

    def __init__(self, workdir: Path, toolsets: "Sequence[str]"):
        self.workdir = workdir
        self._load(toolsets)


def make_box_keeper() -> Any:
    """The thing that keeps boxes between runs, shared across tasks.

    Returned as ``Any`` on purpose: the daemon holds it and hands it back, and
    nothing between here and the executor may learn what is inside it.
    """
    from .docker import BoxKeeper

    return BoxKeeper()


def make_executor(
    workdir: Path,
    toolsets: "Sequence[str]",
    isolation: Isolation | None = None,
    boxes: Any = None,
) -> Executor:
    """The one place that decides where an agent node's tools run.

    Callers hand over a setting and use what comes back, so nothing upstream
    of here names a backend. The Docker import sits inside the branch: a
    machine that never isolates never pays to load it.
    """
    if isolation is None:
        return LocalExecutor(workdir, toolsets)
    from .docker import DockerExecutor

    # With a keeper the box is the task's and survives the run; without one
    # the executor makes its own and destroys it, which is `poieo run`.
    box = boxes.get(workdir, isolation) if boxes is not None else None

    return DockerExecutor(
        workdir,
        toolsets,
        image=isolation.image,
        network=isolation.network,
        user=isolation.user,
        box=box,
    )


# Import toolset modules after Tool is defined, since they import Tool from this module
# (same pattern as pydantic's late rebuild)
from .files import FILES_TOOLS  # noqa: E402
from .shell import SHELL_TOOLS  # noqa: E402

TOOLSETS: dict[str, list[Tool]] = {"files": FILES_TOOLS, "shell": SHELL_TOOLS}
DEFAULT_TOOLSETS: list[str] = ["files", "shell"]
