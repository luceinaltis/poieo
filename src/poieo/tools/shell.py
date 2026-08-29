"""Shell tool. The command's cwd is pinned to the workdir; the command itself
can still name absolute paths -- that boundary needs an OS sandbox, which the
local executor does not claim to be (see the design spec)."""

from __future__ import annotations

import asyncio
import locale
import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any

from ..providers.base import ToolDef
from . import CommandResult, Tool, ToolError

_DEFAULT_TIMEOUT = 120.0
_MAX_TIMEOUT = 600.0


def quote_path(path: str) -> str:
    """A path spelled so the shell that will run it survives it.

    *Which* shell decides the answer, so the answer is given here rather than
    where the path is made. On Windows with a POSIX shell -- now the norm, see
    above -- backslashes are read as escapes and eaten, and a command that is
    one double-quoted word with no space in it loses its quotes before bash
    ever parses it, which fails as an unterminated string. Forward slashes and
    POSIX quoting survive both, with or without a space in the path.

    Without a POSIX shell the reverse holds: `cmd` wants backslashes and does
    not read single quotes as quoting at all.
    """
    if _POSIX_SHELL is None:
        return f'"{path}"'
    # Only on Windows: a backslash is a legal character in a POSIX filename,
    # and rewriting one there would name a different file.
    return shlex.quote(path.replace("\\", "/") if os.name == "nt" else path)
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


def posix_shell(windows: bool = os.name == "nt") -> str | None:
    """A POSIX shell to run commands through, if this machine has one.

    Off POSIX systems there is nothing to look for: `/bin/sh` is what
    `create_subprocess_shell` already uses. On Windows it uses `COMSPEC`,
    which is `cmd.exe` -- and a model writes POSIX, because that is what its
    training and this repository's own documents are written in. A measured
    run watched the model see `grep` and `sed` work (the binaries are on
    PATH), conclude it was on a POSIX system, write a heredoc, and get
    `<<은(는) 예상되지 않았습니다` back.

    **`C:\\Windows\\System32\\bash.exe` is not a candidate.** That is the WSL
    launcher: it starts a Linux distribution with its own filesystem, so the
    `cwd` handed to it points somewhere else entirely -- and the command
    *succeeds* there. Running quietly in the wrong directory is worse than
    failing in the right one.
    """
    if not windows:
        return None
    found = shutil.which("bash")
    if not found:
        return None
    parts = [part.lower() for part in Path(found).parts]
    if "system32" in parts:
        return None
    return found


_POSIX_SHELL = posix_shell()


def _dialect() -> str:
    """One sentence saying what the command will actually be read by.

    Nothing used to say. In a measured run the model watched `grep` and `sed`
    work -- the binaries are on PATH -- concluded it was on a POSIX system,
    wrote a heredoc and got `<<은(는) 예상되지 않았습니다`. Claude Code's own
    shell tool opens by naming its shell for exactly this reason, and this is
    built from what was found rather than hardcoded, so it is a fact about
    this machine rather than a hope about machines in general.
    """
    if os.name != "nt" or _POSIX_SHELL:
        return "Commands are read by a POSIX shell (sh), so POSIX syntax works."
    return (
        "Commands are read by cmd.exe on this machine, NOT a POSIX shell: no "
        "heredocs (`<<`), single quotes do not quote, `NUL` not `/dev/null`, "
        "`%VAR%` not `$VAR`. Unix programs may still be on PATH, so a command "
        "can run while the syntax around it does not."
    )


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
    shared = dict(
        cwd=workdir,
        env=_environment(env),
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=(os.name != "nt"),
    )
    if _POSIX_SHELL:
        # `-c` and not the shell's own parsing of a whole line: the command is
        # one argument, so nothing between here and the shell gets a chance to
        # reinterpret its quoting.
        process = await asyncio.create_subprocess_exec(
            _POSIX_SHELL, "-c", command, **shared
        )
    else:
        process = await asyncio.create_subprocess_shell(command, **shared)
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
                f"{_dialect()} "
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
