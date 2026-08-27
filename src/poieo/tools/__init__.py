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

    Deliberately backend-neutral and free of Docker words: everything
    downstream of a task's ``isolation:`` block sees only this shape.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str
    network: Literal["none", "bridge"] = "none"
    user: str | None = None


@dataclass(slots=True)
class Hands:
    """Everything an agent node's tools need beyond a workdir and a toolset.

    One object rather than one parameter each, threaded from the daemon to the
    executor factory.
    """

    isolation: Isolation | None = None
    # The daemon's box keeper and this task's postbox. Untyped on purpose: only
    # the tools package may know what they are.
    boxes: Any = None
    postbox: Any = None


class Executor:
    """Tool lookup, failure-to-text, and a lifecycle that costs nothing by default.

    Subclasses differ in *where* the tools run, never in what a caller does
    with them: ``async with``, then ``definitions()`` and ``execute()``.
    """

    workdir: Path
    tools: dict[str, Tool]

    def _load(self, toolsets: "Sequence[str]", postbox: Any = None) -> None:
        self.tools = {}
        for name in toolsets:
            entry = TOOLSETS[name]
            # A toolset that must know who is running it is a factory, and is
            # built per executor. The rest are shared module-level lists.
            tools = entry(postbox) if callable(entry) else entry
            for tool in tools:
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

    The default, with nothing to set up or tear down.
    """

    def __init__(
        self, workdir: Path, toolsets: "Sequence[str]", hands: "Hands | None" = None
    ):
        self.workdir = workdir
        self._load(toolsets, hands.postbox if hands else None)


def make_box_keeper() -> Any:
    """The thing that keeps boxes between runs, shared across tasks.

    ``Any`` on purpose: nothing between here and the executor may learn what
    is inside it.
    """
    from .docker import BoxKeeper

    return BoxKeeper()


async def sweep_boxes(days: int = 7) -> int:
    """Reclaim boxes an earlier poieo left behind. Returns how many went.

    A clean shutdown removes every box it owns, so anything still standing is
    from a crash. Safe to run beside another daemon: a box is derived state,
    so the cost of being wrong here is one rebuild.
    """
    from datetime import timedelta

    from .docker import sweep

    return await sweep(older_than=timedelta(days=days))


def make_executor(
    workdir: Path, toolsets: "Sequence[str]", hands: Hands | None = None
) -> Executor:
    """The one place that decides where an agent node's tools run.

    Callers hand over a setting and use what comes back, so nothing upstream
    of here names a backend.
    """
    isolation = hands.isolation if hands else None
    if isolation is None:
        return LocalExecutor(workdir, toolsets, hands)
    # Inside the branch: a machine that never isolates never pays to load it.
    from .docker import DockerExecutor

    # With a keeper the box is the task's and survives the run; without one
    # the executor makes its own and destroys it, which is `poieo run`.
    boxes = hands.boxes if hands else None
    box = boxes.get(workdir, isolation) if boxes is not None else None

    return DockerExecutor(
        workdir,
        toolsets,
        image=isolation.image,
        network=isolation.network,
        user=isolation.user,
        box=box,
        hands=hands,
    )


# Imported after Tool is defined, since they import Tool from this module.
from .files import FILES_TOOLS  # noqa: E402
from .notes import notes_tools  # noqa: E402
from .shell import SHELL_TOOLS  # noqa: E402

# A fixed list, or a factory taking the postbox (see Executor._load).
TOOLSETS: dict[str, Any] = {
    "files": FILES_TOOLS,
    "shell": SHELL_TOOLS,
    "notes": notes_tools,
}
DEFAULT_TOOLSETS: list[str] = ["files", "shell"]
