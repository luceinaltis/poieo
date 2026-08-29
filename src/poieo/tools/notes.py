"""Leaving a line in another task's journal.

One more writer of a file that already exists -- no queue, no inbox. A note is
news rather than an instruction, and it wakes nobody: it is read on the
recipient's next scheduled run, so two tasks writing to each other cannot spin.

Design: docs/tools.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..providers.base import ToolDef
from . import Tool, ToolError


@dataclass(slots=True)
class Postbox:
    """Who is writing, and whose journals they may write to.

    The sender lives here rather than in a tool argument, so a model cannot
    claim to be someone else.
    """

    sender: str
    recipients: dict[str, Path] = field(default_factory=dict)

    def others(self) -> list[str]:
        return sorted(name for name in self.recipients if name != self.sender)


def _tell_tool(postbox: Postbox) -> Tool:
    async def run(_workdir: Path, args: dict[str, Any]) -> str:
        # Late: the journal's format belongs to the task module, and importing
        # it at module level would close a cycle (task imports tools).
        from ..card import append_journal

        name = str(args.get("task", "")).strip()
        message = " ".join(str(args.get("message", "")).split())

        if not message:
            raise ToolError("a note needs something to say")
        if name == postbox.sender:
            raise ToolError("a task does not leave notes for itself; say it in your own summary instead")
        if name not in postbox.recipients:
            known = ", ".join(postbox.others()) or "(none)"
            raise ToolError(f"no task called '{name}'. There is: {known}")

        # The sender is stamped here, never read from the arguments.
        append_journal(postbox.recipients[name], "task", f"[{postbox.sender}] {message}")
        return f"left a note for {name}; it will be read on their next run"

    return Tool(
        ToolDef(
            name="tell",
            description=(
                "Leave a one-line note in another task's journal. They read it "
                "on their next run, not now, and may or may not act on it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Which task to tell."},
                    "message": {"type": "string", "description": "One line."},
                },
                "required": ["task", "message"],
            },
        ),
        run,
    )


def notes_tools(postbox: Postbox | None) -> list[Tool]:
    """Nothing at all without a postbox.

    A half-present tool is worse than an absent one: the model would call it,
    be refused, and spend its turns finding that out.
    """
    if postbox is None:
        return []
    return [_tell_tool(postbox)]
