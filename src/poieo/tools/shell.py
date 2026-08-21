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
