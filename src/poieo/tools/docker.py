"""The container: an executor whose shell can only reach the working directory.

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
import hashlib
import logging
import shlex
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from ..errors import IsolationError
from . import CommandResult, Executor, Isolation, Tool, ToolError
from .shell import _DEFAULT_TIMEOUT, _MAX_TIMEOUT, capped, command_text, decode_output

# A finite sleep, not `sleep infinity`: the latter is a GNU coreutils extension
# that older busybox builds reject, which would exit the container instantly and
# make every later exec fail with an unhelpful "is not running".
_IDLE = "2147483647"
_MOUNT = "/work"
# Where compiled scripts are built and kept, inside the container.
_BUILD = "/tmp/poieo-build"
# How an orphaned container is found after a hard kill, and what the sweep matches on.
BOX_LABEL = "poieo.box"
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
    if not done.stdout.strip():
        # `docker info` exits 0 with an unreachable daemon on Windows and puts
        # the failure on stderr, so the version being empty is the real signal.
        # Reported plainly rather than by quoting docker's named-pipe error: the
        # user's next move is to start Docker, not to read a URL.
        return False, "the docker daemon is not running"
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


async def _docker(*args: str, timeout: float = _PROBE_TIMEOUT, stdin: str | None = None) -> tuple[int, str]:
    """Run a docker command off the event loop's back."""
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(stdin.encode() if stdin is not None else None), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise
    return process.returncode or 0, decode_output(stdout)


def _resolved(workdir: Path) -> Path:
    # Docker reads a relative or ~-prefixed source as a *named volume*: the
    # container starts fine, /work is empty, and the model reports that the
    # project does not exist. Resolve before it can happen.
    return Path(workdir).expanduser().resolve()


async def _start(workdir: Path, isolation: Isolation, labels: dict[str, str] | None = None) -> str:
    """Start one detached container and return its id."""
    workdir = _resolved(workdir)
    if not workdir.is_dir():
        raise IsolationError(f"workdir is not a directory: {workdir}")
    args = [
        "run",
        "-d",
        "--rm",
        "-v",
        f"{workdir}:{_MOUNT}",
        "-w",
        _MOUNT,
        "--network",
        isolation.network,
    ]
    if isolation.user:
        args += ["--user", isolation.user]
    for key, value in (labels or {}).items():
        args += ["--label", f"{key}={value}"]
    args += [isolation.image, "sleep", _IDLE]

    code, out = await _docker(*args)
    if code != 0:
        raise IsolationError(f"could not start an isolated environment: {out.strip()}")
    return out.strip().splitlines()[-1]


async def _alive(container_id: str) -> bool:
    code, out = await _docker("inspect", "-f", "{{.State.Running}}", container_id)
    return code == 0 and out.strip() == "true"


async def _remove(container_id: str) -> None:
    """Never raises: a container that will not die must not take a run down with it."""
    try:
        await _docker("rm", "-f", container_id)
    except Exception as failure:
        log.warning("could not remove container %s: %s", container_id, failure)


class Container:
    """One task's isolated environment, kept between that task's runs.

    *Derived state*: removing it is always allowed and the next run rebuilds
    it. Owned by whatever outlives a run; executors borrow it and must never
    remove it.
    """

    def __init__(self, key: str, workdir: Path, isolation: Isolation):
        self.key = key
        self.workdir = _resolved(workdir)
        self.isolation = isolation
        self.container_id: str | None = None

    async def ensure(self) -> str:
        """The container id, starting one if it is missing or has died.

        Idempotent and deliberately tolerant: a machine that slept, a docker
        restart or a hand-run `docker rm` all land here as a rebuild. Changed
        settings do not -- the keeper keys a container by them, so an edited
        isolation block gets a different container rather than reconfiguring this.
        """
        if self.container_id and await _alive(self.container_id):
            return self.container_id
        self.container_id = await _start(self.workdir, self.isolation, {BOX_LABEL: self.key})
        return self.container_id

    async def remove(self) -> None:
        container_id, self.container_id = self.container_id, None
        if container_id:
            await _remove(container_id)


async def sweep(older_than: timedelta) -> int:
    """Remove poieo containers older than ``older_than``. Returns how many went.

    Looks at every labelled container, not only this process's, so it also
    reclaims disk from tasks deleted while the daemon was down.

    An *age* cap, not an idle one: docker records when a container was created,
    not when it was last used. For an hourly task the difference is one rebuild
    a week.
    """
    code, out = await _docker("ps", "-aq", "--no-trunc", "--filter", f"label={BOX_LABEL}")
    if code != 0:
        return 0
    removed = 0
    cutoff = datetime.now(timezone.utc) - older_than
    for container_id in out.split():
        code, created = await _docker("inspect", "-f", "{{.Created}}", container_id)
        if code != 0:
            continue
        if _created_at(created) <= cutoff:
            await _remove(container_id)
            removed += 1
    return removed


def _created_at(raw: str) -> datetime:
    """Parse docker's RFC3339Nano timestamp.

    Truncated to seconds because 3.10's fromisoformat rejects both nanosecond
    precision and a trailing Z.
    """
    stamp = raw.strip()[:19]
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        # Unparseable means unknown age; treat it as new so a sweep never
        # removes something it does not understand.
        return datetime.now(timezone.utc)


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
        container: "Container | None" = None,
        tool_context: Any = None,
    ):
        self.workdir = _resolved(workdir)
        self.isolation = Isolation(image=image, network=network, user=user)
        self.labels = dict(labels or {})
        # Handed a container, this executor borrows it and must not remove it; the
        # owner outlives the run. Without one it creates and destroys its own,
        # which is the one-shot `poieo run` path.
        self.container = container
        self.container_id: str | None = None

        self._load(toolsets, tool_context.postbox if tool_context else None)
        # The one substitution this class exists to make.
        if "run_command" in self.tools:
            self.tools["run_command"] = Tool(self.tools["run_command"].definition, self._run_command_in_box)

    # -- lifecycle -----------------------------------------------------------
    async def __aenter__(self) -> "DockerExecutor":
        if self.container is not None:
            self.container_id = await self.container.ensure()
        else:
            self.container_id = await _start(self.workdir, self.isolation, self.labels)
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        container_id, self.container_id = self.container_id, None
        # A borrowed container outlives this run; removing it here would be the
        # borrower destroying the lender's object, and every single-run test
        # would still pass.
        if container_id and self.container is None:
            await _remove(container_id)

    # -- execution -----------------------------------------------------------
    # execute() and definitions() are inherited: the contract is identical, and
    # only the tool bound to run_command differs.

    async def run_command(
        self,
        command: str,
        timeout: float | None = None,
        env: Any = None,
        stdin: str | None = None,
    ) -> CommandResult:
        """The seam, entered directly -- and it lands *inside the box*.

        A caller that shelled out itself would run on the host here, which is
        the one thing a task asking to be fenced must never get.
        """
        if not self.container_id:
            raise ToolError("the isolated environment is not running")
        seconds = min(float(_DEFAULT_TIMEOUT if timeout is None else timeout), _MAX_TIMEOUT)
        # `-i` or the interpreter reads an empty stdin and exits 0 having run
        # nothing -- success reported over no work.
        argv = ["exec", "-w", _MOUNT] + (["-i"] if stdin is not None else [])
        for key, value in (env or {}).items():
            argv += ["-e", f"{key}={value}"]
        try:
            code, text = await _docker(
                *argv,
                self.container_id,
                "sh",
                "-c",
                command,
                timeout=seconds,
                stdin=stdin,
            )
        except asyncio.TimeoutError:
            raise ToolError(f"command timed out after {seconds:.0f}s: {command}")
        return CommandResult(exit_code=code, output=capped(text))

    def build_paths(self, key: str, source: str) -> tuple[str, str]:
        """Built things live **inside the container**, not on a mounted folder.

        Two reasons, and the second is the one that would bite. It needs no
        second mount -- and a binary built here is for the image's platform,
        so a cache shared with the host would eventually hand a Windows
        executable to a Linux container.

        Its lifetime is the container's, which is the lifetime of everything
        else that container installed: kept between runs, gone when the daemon
        stops or `poieo reset` throws it away. No new contract to explain.
        """
        home = f"{_BUILD}/{key}"
        return f"{home}/{source}", f"{home}/prog"

    async def _is_built(self, binary: str) -> bool:
        code, _ = await self._exec(f"test -x {self.quote(binary)}")
        return code == 0

    def quote(self, path: str) -> str:
        """POSIX quoting, always: whatever the host is, the box is Linux."""
        return shlex.quote(path)

    async def _put(self, path: str, content: str) -> None:
        parent = path.rsplit("/", 1)[0]
        code, out = await self._exec(f"mkdir -p {self.quote(parent)} && cat > {self.quote(path)}", stdin=content)
        if code != 0:
            raise ToolError(f"could not write {path} in the box: {out.strip()}")

    async def _exec(self, command: str, stdin: str | None = None) -> tuple[int, str]:
        """One `docker exec` of a shell line, without the CommandResult shaping."""
        if not self.container_id:
            raise ToolError("the isolated environment is not running")
        argv = ["exec", "-w", _MOUNT] + (["-i"] if stdin is not None else [])
        return await _docker(*argv, self.container_id, "sh", "-c", command, stdin=stdin)

    async def _run_command_in_box(self, _workdir: Path, args: dict[str, Any]) -> str:
        return await command_text(self.run_command, args)


def container_key(workdir: Path, isolation: Isolation) -> str:
    """What makes two containers the same container: folder and settings, nothing about
    who asked -- so two tasks over one repo share a toolchain."""
    raw = f"{workdir}|{isolation.image}|{isolation.network}|{isolation.user}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class ContainerPool:
    """Every container this daemon keeps, one per (folder, settings).

    Sharing has a cost worth knowing: tasks in one container can disturb each other,
    because the container is one machine. What they cannot disturb is anything
    outside the folder, which is the boundary that matters.

    Held by the Daemon and handed down as an opaque object.
    """

    def __init__(self) -> None:
        self.containers: dict[str, Container] = {}

    def get(self, workdir: Path, isolation: Isolation) -> Container:
        workdir = _resolved(workdir)
        key = container_key(workdir, isolation)
        container = self.containers.get(key)
        if container is None:
            container = self.containers[key] = Container(key, workdir, isolation)
        return container

    async def aclose(self) -> None:
        for container in list(self.containers.values()):
            await container.remove()
        self.containers.clear()


def remove_containers_for(workdir: Path) -> int:
    """Throw away every container built around ``workdir``. Returns how many went.

    Synchronous and label-driven, because `poieo reset` runs with no daemon and
    no event loop, and must reach containers this process never started. Nothing
    inside the folder is touched.
    """
    # Matched on the mount rather than the key: reset knows the folder but not
    # which image or network the container was built with.
    workdir = _resolved(workdir)
    listed = subprocess.run(
        ["docker", "ps", "-aq", "--no-trunc", "--filter", f"label={BOX_LABEL}"],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT,
    )
    if listed.returncode != 0:
        return 0
    removed = 0
    for container_id in listed.stdout.split():
        shown = subprocess.run(
            ["docker", "inspect", "-f", "{{range .Mounts}}{{.Source}}{{end}}", container_id],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
        if shown.returncode != 0 or shown.stdout.strip() != str(workdir):
            continue
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
        removed += 1
    return removed
