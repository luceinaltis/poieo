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
