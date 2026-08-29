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
from . import CommandResult, Tool, ToolError

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


def _environment(extra: Any) -> dict[str, str] | None:
    """The process environment with `extra` laid over it, or None for as-is.

    Added to rather than replacing: a command with no PATH cannot find the
    program it was asked to run. Values are coerced because JSON has numbers
    and an environment does not -- a model writing `{"RETRIES": 3}` should get
    a variable, not a TypeError from inside the tool.
    """
    if not isinstance(extra, dict) or not extra:
        return None
    return {**os.environ, **{str(k): str(v) for k, v in extra.items()}}


async def run_here(
    workdir: Path,
    command: str,
    timeout: float = _DEFAULT_TIMEOUT,
    env: Any = None,
    stdin: str | None = None,
) -> CommandResult:
    """Run one command on this machine and report what it did.

    The exit code comes back as the **number the process returned**. Formatting
    it into a sentence is the tool's job, one caller up: a model reads text, a
    router reads a number, and only one of those two readings can be got wrong.
    """
    timeout = min(float(timeout), _MAX_TIMEOUT)
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=workdir,
        env=_environment(env),
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=(os.name != "nt"),
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(stdin.encode() if stdin is not None else None), timeout
        )
    except asyncio.TimeoutError:
        _kill_tree(process)
        await process.communicate()
        # Not an exit code: "this never finished" and "this finished badly" are
        # different facts, and a caller has to be able to tell them apart.
        raise ToolError(f"command timed out after {timeout:.0f}s: {command}")
    try:
        text = stdout.decode()
    except UnicodeDecodeError:
        text = stdout.decode(locale.getpreferredencoding(False), errors="replace")
    if len(text) > _OUTPUT_CAP:
        text = text[:_OUTPUT_CAP] + "\n... [output truncated]"
    return CommandResult(exit_code=process.returncode or 0, output=text)


async def _run_command(workdir: Path, args: dict[str, Any]) -> str:
    """The same run, shaped for a model to read."""
    result = await run_here(
        workdir,
        str(args["command"]),
        timeout=float(args.get("timeout", _DEFAULT_TIMEOUT)),
        env=args.get("env"),
    )
    return result.as_text()


SHELL_TOOLS: list[Tool] = [
    Tool(
        ToolDef(
            name="run_command",
            description=(
                "Run a shell command in the working directory. Returns the exit "
                "code and combined stdout/stderr. This is for running programs "
                "-- tests, git, a build. To read, search or change a file, use "
                "the file tools instead: they do not depend on which shell this "
                "machine has. Use `env` to set variables for the command rather "
                "than writing them into it: shells disagree about how that is "
                "spelled, and getting it wrong looks exactly like the command "
                "running and failing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "env": {
                        "type": "object",
                        "description": (
                            "Variables to set for this command only, laid over "
                            "the environment rather than replacing it."
                        ),
                    },
                    "timeout": {"type": "number", "description": "seconds, max 600"},
                },
                "required": ["command"],
            },
        ),
        _run_command,
    ),
]
