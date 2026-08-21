"""Shell tool. The command's cwd is pinned to the workdir; the command itself
can still name absolute paths -- that boundary needs an OS sandbox, which the
local executor does not claim to be (see the design spec)."""

from __future__ import annotations

import asyncio
import locale
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from ..providers.base import ToolDef
from . import Tool, ToolError

_DEFAULT_TIMEOUT = 120.0
_MAX_TIMEOUT = 600.0
_OUTPUT_CAP = 20_000


def _kill_tree(process: asyncio.subprocess.Process) -> None:
    """Kill the shell and everything it spawned."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


async def _run_command(workdir: Path, args: dict[str, Any]) -> str:
    command = str(args["command"])
    timeout = min(float(args.get("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=workdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=(os.name != "nt"),
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        _kill_tree(process)
        await process.communicate()
        raise ToolError(f"command timed out after {timeout:.0f}s: {command}")
    try:
        text = stdout.decode()
    except UnicodeDecodeError:
        text = stdout.decode(locale.getpreferredencoding(False), errors="replace")
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
