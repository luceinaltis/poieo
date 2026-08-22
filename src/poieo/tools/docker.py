"""The box: an executor whose shell can only reach the working directory.

This is the only module in poieo that knows Docker exists. File tools are the
host implementations, unchanged -- ``resolve_path`` already confines them, and
routing them through ``docker exec`` would add quoting, encoding and ownership
bugs to code whose blast radius is already correct. The hole is
``run_command``, so ``run_command`` is what gets a container.

The workdir is bind-mounted rather than copied: host file tools and the
container's shell must see the same bytes at the same instant, or the model
writes a file it then cannot compile.
"""

from __future__ import annotations

import asyncio
import locale
import logging
import subprocess
from pathlib import Path
from typing import Any, Sequence

from ..errors import IsolationError
from . import Executor, Tool, ToolError
from .shell import _MAX_TIMEOUT, _OUTPUT_CAP, _DEFAULT_TIMEOUT

# A finite sleep, not `sleep infinity`: the latter is a GNU coreutils extension
# that older busybox builds reject, which would exit the container instantly and
# make every later exec fail with an unhelpful "is not running".
_IDLE = "2147483647"
_MOUNT = "/work"
_PROBE_TIMEOUT = 20.0

log = logging.getLogger("poieo.isolation")


def docker_available() -> tuple[bool, str]:
    """Is there a docker we can actually run containers on?

    Returns ``(False, reason)`` rather than raising, because every caller wants
    to turn the reason into its own kind of message. The reason names Docker
    directly -- it is a configuration string, never an interface string.
    """
    try:
        done = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except FileNotFoundError:
        return False, "docker is not on PATH"
    except subprocess.TimeoutExpired:
        return False, "docker did not respond"
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        return False, detail[-1] if detail else "the docker daemon is not running"
    return True, ""


def image_present(image: str) -> bool:
    """Is ``image`` already local? poieo never pulls on the user's behalf."""
    try:
        done = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


async def _docker(*args: str, timeout: float = _PROBE_TIMEOUT) -> tuple[int, str]:
    """Run a docker command off the event loop's back."""
    process = await asyncio.create_subprocess_exec(
        "docker", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise
    return process.returncode or 0, _decode(stdout)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode()
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors="replace")


class DockerExecutor(Executor):
    """The same executor contract, with the shell inside a container.

    Enter it before use -- ``execute()`` outside the context manager reports a
    tool error, never a quiet fall back to the host.
    """

    def __init__(
        self,
        workdir: Path,
        toolsets: Sequence[str],
        *,
        image: str,
        network: str = "none",
        user: str | None = None,
        labels: dict[str, str] | None = None,
    ):
        # Docker reads a relative or ~-prefixed source as a *named volume*: the
        # container starts fine, /work is empty, and the model reports that the
        # project does not exist. Resolve before it can happen.
        self.workdir = Path(workdir).expanduser().resolve()
        self.image = image
        self.network = network
        self.user = user
        self.labels = dict(labels or {})
        self.container_id: str | None = None

        self._load(toolsets)
        # The one substitution this class exists to make.
        if "run_command" in self.tools:
            self.tools["run_command"] = Tool(
                self.tools["run_command"].definition, self._run_command_in_box
            )

    # -- lifecycle -----------------------------------------------------------
    async def __aenter__(self) -> "DockerExecutor":
        if not self.workdir.is_dir():
            raise IsolationError(f"workdir is not a directory: {self.workdir}")
        args = [
            "run", "-d", "--rm",
            "-v", f"{self.workdir}:{_MOUNT}",
            "-w", _MOUNT,
            "--network", self.network,
        ]
        if self.user:
            args += ["--user", self.user]
        for key, value in self.labels.items():
            args += ["--label", f"{key}={value}"]
        args += [self.image, "sleep", _IDLE]

        code, out = await _docker(*args)
        if code != 0:
            raise IsolationError(
                f"could not start an isolated environment: {out.strip()}"
            )
        self.container_id = out.strip().splitlines()[-1]
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        container_id, self.container_id = self.container_id, None
        if not container_id:
            return
        try:
            await _docker("rm", "-f", container_id)
        except Exception as failure:
            # Teardown must never replace the exception that got us here, but a
            # leaked container is not allowed to be silent either. The
            # poieo.run_id label is how it is found afterwards.
            log.warning("could not remove container %s: %s", container_id, failure)

    # -- execution -----------------------------------------------------------
    # execute() and definitions() are inherited: the contract is identical, and
    # only the tool bound to run_command differs.

    async def _run_command_in_box(self, _workdir: Path, args: dict[str, Any]) -> str:
        if not self.container_id:
            raise ToolError("the isolated environment is not running")
        command = str(args["command"])
        timeout = min(float(args.get("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)
        try:
            code, text = await _docker(
                "exec", "-w", _MOUNT, self.container_id, "sh", "-c", command,
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ToolError(f"command timed out after {timeout:.0f}s: {command}")
        if len(text) > _OUTPUT_CAP:
            text = text[:_OUTPUT_CAP] + "\n... [output truncated]"
        return f"exit code: {code}\n{text}"

