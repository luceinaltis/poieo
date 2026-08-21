"""Tools an agent node may hand to its model, and the executor that runs them.

A node never touches the filesystem or a subprocess directly: it hands the
model's :class:`~poieo.providers.base.ToolCall`s to an executor and gets text
back. Tool *failures* become error text for the model to read and correct --
only harness bugs raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

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


# Import toolset modules after Tool is defined, since they import Tool from this module
# (same pattern as pydantic's late rebuild)
from .files import FILES_TOOLS  # noqa: E402
from .shell import SHELL_TOOLS  # noqa: E402

TOOLSETS: dict[str, list[Tool]] = {"files": FILES_TOOLS, "shell": SHELL_TOOLS}
DEFAULT_TOOLSETS: list[str] = ["files", "shell"]
