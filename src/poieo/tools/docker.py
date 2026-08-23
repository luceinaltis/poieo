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
import hashlib
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from ..errors import IsolationError
from . import Executor, Isolation, Tool, ToolError
from .shell import _MAX_TIMEOUT, _OUTPUT_CAP, _DEFAULT_TIMEOUT

# A finite sleep, not `sleep infinity`: the latter is a GNU coreutils extension
# that older busybox builds reject, which would exit the container instantly and
# make every later exec fail with an unhelpful "is not running".
_IDLE = "2147483647"
_MOUNT = "/work"
# How an orphaned box is found after a hard kill, and what the sweep matches on.
LABEL_BOX = "poieo.box"
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


def _resolved(workdir: Path) -> Path:
    # Docker reads a relative or ~-prefixed source as a *named volume*: the
    # container starts fine, /work is empty, and the model reports that the
    # project does not exist. Resolve before it can happen.
    return Path(workdir).expanduser().resolve()


async def _start(
    workdir: Path, isolation: Isolation, labels: dict[str, str] | None = None
) -> str:
    """Start one detached container and return its id."""
    workdir = _resolved(workdir)
    if not workdir.is_dir():
        raise IsolationError(f"workdir is not a directory: {workdir}")
    args = [
        "run", "-d", "--rm",
        "-v", f"{workdir}:{_MOUNT}",
        "-w", _MOUNT,
        "--network", isolation.network,
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
    """Never raises: a box that will not die must not take a run down with it."""
    try:
        await _docker("rm", "-f", container_id)
    except Exception as failure:
        log.warning("could not remove container %s: %s", container_id, failure)


class Box:
    """One task's isolated environment, kept between that task's runs.

    A task accumulates on purpose -- its journal is re-read before every run,
    its private working copy persists -- so its box does too. What makes that
    safe is that the box is *derived state*: removing it is always allowed, and
    the next run rebuilds it.

    Owned by whatever outlives a run (the daemon's FlowRunner). Executors
    borrow it and must never remove it.
    """

    def __init__(self, key: str, workdir: Path, isolation: Isolation):
        self.key = key
        self.workdir = _resolved(workdir)
        self.isolation = isolation
        self.container_id: str | None = None

    def matches(self, isolation: Isolation) -> bool:
        """False once the task asks for something this box is not."""
        return self.isolation == isolation

    async def ensure(self, isolation: Isolation | None = None) -> str:
        """The container id, starting one if it is missing, dead, or now wrong.

        Idempotent, and deliberately tolerant: a machine that slept, a docker
        restart, someone running `docker rm` by hand, or an edited isolation
        block all land here as a rebuild rather than a failure.
        """
        if isolation is not None and isolation != self.isolation:
            await self.remove()
            self.isolation = isolation
        if self.container_id and await _alive(self.container_id):
            return self.container_id
        self.container_id = await _start(
            self.workdir, self.isolation, {LABEL_BOX: self.key}
        )
        return self.container_id

    async def remove(self) -> None:
        container_id, self.container_id = self.container_id, None
        if container_id:
            await _remove(container_id)


async def sweep(older_than: timedelta) -> int:
    """Remove poieo boxes older than ``older_than``. Returns how many went.

    Bounds how far a kept box can drift, and reclaims disk from tasks that were
    deleted while the daemon was down -- so it looks at every labelled
    container, not only the ones this process started.

    This is an *age* cap, not an idle one: docker records when a container was
    created, not when it was last used, and inventing a last-used file inside
    each box would be more machinery than the problem deserves. For a task on
    an hourly trigger the difference is one rebuild a week, which is the drift
    ceiling working rather than a cost.
    """
    code, out = await _docker("ps", "-aq", "--no-trunc", "--filter", f"label={LABEL_BOX}")
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
        box: "Box | None" = None,
    ):
        self.workdir = _resolved(workdir)
        self.image = image
        self.network = network
        self.user = user
        self.labels = dict(labels or {})
        # Handed a box, this executor borrows it and must not remove it; the
        # owner outlives the run. Without one it creates and destroys its own,
        # which is the one-shot `poieo run` path.
        self.box = box
        self.container_id: str | None = None

        self._load(toolsets)
        # The one substitution this class exists to make.
        if "run_command" in self.tools:
            self.tools["run_command"] = Tool(
                self.tools["run_command"].definition, self._run_command_in_box
            )

    def _isolation(self) -> Isolation:
        return Isolation(image=self.image, network=self.network, user=self.user)

    # -- lifecycle -----------------------------------------------------------
    async def __aenter__(self) -> "DockerExecutor":
        if self.box is not None:
            self.container_id = await self.box.ensure(self._isolation())
        else:
            self.container_id = await _start(self.workdir, self._isolation(), self.labels)
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        container_id, self.container_id = self.container_id, None
        # A borrowed box outlives this run; removing it here would be the
        # borrower destroying the lender's object, and every single-run test
        # would still pass.
        if container_id and self.box is None:
            await _remove(container_id)

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



def box_key(workdir: Path, isolation: Isolation) -> str:
    """What makes two boxes the same box.

    Folder and settings, nothing about who asked. Two tasks standing over one
    repo -- keep the tests green, keep the docs current -- are the common case,
    and giving them a box each would mean installing the same toolchain twice.
    """
    raw = f"{workdir}|{isolation.image}|{isolation.network}|{isolation.user}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class BoxKeeper:
    """Every box this daemon keeps, shared by whatever tasks want the same one.

    One box per (folder, settings), the way the daemon already keeps one
    provider pool per binding file. Sharing is implicit and has a cost worth
    knowing: tasks in one box can disturb each other, because the box is one
    machine. What they cannot disturb is anything outside the folder, which is
    the boundary this whole slice is about.

    Held by the Daemon, which outlives every run of every task. Handed down as
    an opaque object -- nothing between here and the executor learns what it
    is.
    """

    def __init__(self) -> None:
        self.boxes: dict[str, Box] = {}

    def get(self, workdir: Path, isolation: Isolation) -> Box:
        workdir = _resolved(workdir)
        key = box_key(workdir, isolation)
        box = self.boxes.get(key)
        if box is None:
            box = self.boxes[key] = Box(key, workdir, isolation)
        return box

    async def aclose(self) -> None:
        for box in list(self.boxes.values()):
            await box.remove()
        self.boxes.clear()


def remove_boxes_for(workdir: Path) -> int:
    """Throw away every box built around ``workdir``. Returns how many went.

    Synchronous and label-driven, because `poieo reset` runs with no daemon and
    no event loop: it must reach boxes this process never started.

    Nothing inside the folder is touched. That is the whole promise of the
    command, and the reason it is safe to suggest whenever a task starts
    behaving oddly.
    """
    # Matched on the mount rather than the key: reset knows the folder but not
    # which image or network the box was built with.
    workdir = _resolved(workdir)
    listed = subprocess.run(
        ["docker", "ps", "-aq", "--no-trunc", "--filter", f"label={LABEL_BOX}"],
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
