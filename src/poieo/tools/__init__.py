"""Tools an agent node may hand to its model, and the executor that runs them.

A node never touches the filesystem or a subprocess directly: it hands the
model's :class:`~poieo.providers.base.ToolCall`s to an executor and gets text
back. Tool *failures* become error text for the model to read and correct --
only harness bugs raise.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict

from ..errors import PoieoError
from ..providers.base import ToolCall, ToolDef


class ToolError(PoieoError):
    """An expected tool failure, reported back to the model as text."""


@dataclass(slots=True)
class ToolResult:
    text: str
    error: bool = False


# How to hand a script to an interpreter: the argv that reads it from stdin.
#
# Stdin, not a file. A file would have to live in the workdir for a container
# to see it, and the workdir is committed whole as the night's change -- so a
# scratch file would arrive in somebody's diff. Going through stdin also keeps
# the code away from a shell, which is what stops a quote, a colon or a newline
# from meaning something on the way past.
#
# Adding a language is a line. An interpreter that is not installed fails with
# its own message, which is the honest report.
LANGUAGES: dict[str, list[str]] = {
    "python": ["python", "-"],
    "node": ["node", "-"],
    "sh": ["sh", "-"],
}


@dataclass(frozen=True)
class Compiled:
    """A language that wants a path before it will do anything.

    ``build`` names the compiler with ``{src}`` and ``{bin}`` to fill in.
    Nothing here knows where those paths are: that is the executor's business,
    because where a thing is built is where it has to run.
    """

    source: str
    build: tuple[str, ...]


# A compiler cannot read from stdin, so these need a file somewhere -- and once
# there is a somewhere, naming it by the hash of what goes in it *is* the cache.
# Skipping the build is then one `if it is already there`.
COMPILED: dict[str, Compiled] = {
    "c": Compiled("main.c", ("cc", "-O2", "-o", "{bin}", "{src}")),
    "go": Compiled("main.go", ("go", "build", "-o", "{bin}", "{src}")),
    "rust": Compiled("main.rs", ("rustc", "-O", "-o", "{bin}", "{src}")),
}


def known_language(name: str) -> bool:
    return name in LANGUAGES or name in COMPILED


def is_compiled(name: str) -> bool:
    """Whether this language is built before it runs -- and so is cached.

    Callers outside this package ask this rather than reading `COMPILED`: what
    they want to know is whether the text is a program or a template, which is
    a smaller question than what to do about it.
    """
    return name in COMPILED


def cache_key(language: str, script: str) -> str:
    """Same code, same language, same name -- as `blob.py` names its keepsakes.

    The toolchain's version is deliberately absent. Upgrading a compiler over
    unchanged source almost never changes what the program does, both caches
    carry a "delete freely" contract already, and reading a version would cost
    a process on every *hit* -- which is the cost this exists to remove.
    """
    return hashlib.sha256(f"{language}\0{script}".encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class CommandResult:
    """What a command did, as the two facts the machine actually knows.

    ``exit_code`` is the number the process returned, not a sentence about it.
    That distinction is the whole reason this type exists: a model reads text
    and can misread it, and anything branching on "did this pass" should be
    reading the number the process gave.
    """

    exit_code: int
    output: str

    def as_text(self) -> str:
        """The same result, shaped for a model to read."""
        return f"exit code: {self.exit_code}\n{self.output}"


@dataclass(slots=True)
class Tool:
    """A declaration plus the coroutine that executes it inside a workdir."""

    definition: ToolDef
    run: Callable[[Path, dict[str, Any]], Awaitable[str]]


class Isolation(BaseModel):
    """Where a task's shell commands may run.

    Deliberately backend-neutral and free of Docker words: everything
    downstream of a task's ``isolation:`` block sees only this shape.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str
    network: Literal["none", "bridge"] = "none"
    user: str | None = None


@dataclass(slots=True)
class ToolContext:
    """Everything an agent node's tools need beyond a workdir and a toolset.

    One object rather than one parameter each, threaded from the daemon to the
    executor factory.
    """

    isolation: Isolation | None = None
    # The daemon's container keeper and this task's postbox. Untyped on purpose: only
    # the tools package may know what they are.
    containers: Any = None
    postbox: Any = None
    # Where a compiled script's source and binary are kept, on this machine.
    # The project's `memory/cache/`, which is gitignored and safe to delete.
    #
    # Passed in rather than derived from the workdir, and that is not fussiness:
    # `layout_for()` answers with the workdir *itself* when it holds no
    # `poieo.yaml`, so a cache worked out from there would land inside the
    # user's repository -- which is committed whole as the night's change.
    build_cache: Path | None = None


class Executor:
    """Tool lookup, failure-to-text, and a lifecycle that costs nothing by default.

    Subclasses differ in *where* the tools run, never in what a caller does
    with them: ``async with``, then ``definitions()`` and ``execute()``.
    """

    workdir: Path
    tools: dict[str, Tool]

    def _load(self, toolsets: "Sequence[str]", postbox: Any = None) -> None:
        self.tools = {}
        for name in toolsets:
            entry = TOOLSETS[name]
            # A toolset that must know who is running it is a factory, and is
            # built per executor. The rest are shared module-level lists.
            tools = entry(postbox) if callable(entry) else entry
            for tool in tools:
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

    async def run_command(
        self,
        command: str,
        timeout: float | None = None,
        env: Any = None,
        stdin: str | None = None,
    ) -> CommandResult:
        """Run one command **where this executor runs things**, and report it.

        The same seam the model's `run_command` tool goes through, entered
        directly. A caller that shelled out itself would work on a host and
        quietly escape the box on a task that asked to be fenced -- half a
        fence being worse than none, since nobody knows which half.
        """
        raise NotImplementedError

    async def run_script(
        self, language: str, script: str, timeout: float | None = None, env: Any = None
    ) -> CommandResult:
        """Run code in a named language, where this executor runs things.

        An interpreted language reads it from stdin and leaves nothing behind.
        A compiled one cannot -- a compiler wants a path -- so it is written,
        built and run under :meth:`build_paths`, keyed by the hash of the code.
        The build is skipped when the binary from that hash is already there.

        Languages live here rather than in the node because *where a thing is
        built is where it has to run*: a binary made on this host will not run
        in a Linux container, and only the executor knows which it is.
        """
        if language in LANGUAGES:
            return await self.run_command(
                " ".join(LANGUAGES[language]), timeout=timeout, env=env, stdin=script
            )
        spec = COMPILED[language]
        source, binary = self.build_paths(cache_key(language, script), spec.source)

        if not await self._is_built(binary):
            await self._put(source, script)
            built = await self.run_command(
                " ".join(spec.build).format(
                    src=self.quote(source), bin=self.quote(binary)
                ),
                timeout=timeout,
            )
            if built.exit_code != 0:
                # The compiler's own words. A build that failed is a fact for a
                # router exactly as a red test suite is.
                return built

        return await self.run_command(self.quote(binary), timeout=timeout, env=env)

    def build_paths(self, key: str, source: str) -> tuple[str, str]:
        """Where this key's source and binary live, spelled for this filesystem.

        Each executor answers for its own: a container is posix whatever the
        host is, and a host path built with forward slashes reads wrong in
        every error message it appears in.
        """
        raise NotImplementedError

    def quote(self, path: str) -> str:
        """The same path, spelled for the shell this executor commands.

        Alongside :meth:`build_paths` and for the same reason: only the
        executor knows which shell reads what it hands over, and a path is
        quoted differently for each.
        """
        raise NotImplementedError

    async def _is_built(self, binary: str) -> bool:
        raise NotImplementedError

    async def _put(self, path: str, content: str) -> None:
        raise NotImplementedError

    async def __aenter__(self) -> "Executor":
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        return None


class LocalExecutor(Executor):
    """Runs tool calls directly on this machine, confined to one workdir.

    The default, with nothing to set up or tear down.
    """

    def __init__(
        self, workdir: Path, toolsets: "Sequence[str]", tool_context: "ToolContext | None" = None
    ):
        self.workdir = workdir
        self._cache = tool_context.build_cache if tool_context else None
        self._load(toolsets, tool_context.postbox if tool_context else None)

    def build_paths(self, key: str, source: str) -> tuple[str, str]:
        # Outside any project -- `poieo run` from a bare folder -- the OS's
        # temp directory, which is transient by definition and, crucially, is
        # not inside somebody's repository.
        root = self._cache or Path(tempfile.gettempdir()) / "poieo-build"
        home = root / key
        return str(home / source), str(home / "prog")

    def quote(self, path: str) -> str:
        from .shell import quote_path

        return quote_path(path)

    async def _is_built(self, binary: str) -> bool:
        return Path(binary).is_file()

    async def _put(self, path: str, content: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # tmp-then-rename, as `blob.py` writes its keepsakes: a torn write must
        # not leave a wrong body under a right name, which here would mean
        # building yesterday's code and calling it today's.
        temp = target.with_name(f".{target.name}.tmp")
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, target)

    async def run_command(
        self,
        command: str,
        timeout: float | None = None,
        env: Any = None,
        stdin: str | None = None,
    ) -> CommandResult:
        from .shell import _DEFAULT_TIMEOUT, run_here

        return await run_here(
            self.workdir,
            command,
            timeout=_DEFAULT_TIMEOUT if timeout is None else timeout,
            env=env,
            stdin=stdin,
        )


def make_container_pool() -> Any:
    """The thing that keeps containers between runs, shared across tasks.

    ``Any`` on purpose: nothing between here and the executor may learn what
    is inside it.
    """
    from .docker import ContainerPool

    return ContainerPool()


async def sweep_containers(days: int = 7) -> int:
    """Reclaim containers an earlier poieo left behind. Returns how many went.

    A clean shutdown removes every container it owns, so anything still standing is
    from a crash. Safe to run beside another daemon: a container is derived state,
    so the cost of being wrong here is one rebuild.
    """
    from datetime import timedelta

    from .docker import sweep

    return await sweep(older_than=timedelta(days=days))


def make_executor(
    workdir: Path, toolsets: "Sequence[str]", tool_context: ToolContext | None = None
) -> Executor:
    """The one place that decides where an agent node's tools run.

    Callers hand over a setting and use what comes back, so nothing upstream
    of here names a backend.
    """
    isolation = tool_context.isolation if tool_context else None
    if isolation is None:
        return LocalExecutor(workdir, toolsets, tool_context)
    # Inside the branch: a machine that never isolates never pays to load it.
    from .docker import DockerExecutor

    # With a keeper the container is the task's and survives the run; without one
    # the executor makes its own and destroys it, which is `poieo run`.
    containers = tool_context.containers if tool_context else None
    container = containers.get(workdir, isolation) if containers is not None else None

    return DockerExecutor(
        workdir,
        toolsets,
        image=isolation.image,
        network=isolation.network,
        user=isolation.user,
        container=container,
        tool_context=tool_context,
    )


# Imported after Tool is defined, since they import Tool from this module.
from .files import FILES_TOOLS  # noqa: E402
from .notes import notes_tools  # noqa: E402
from .shell import SHELL_TOOLS  # noqa: E402

# A fixed list, or a factory taking the postbox (see Executor._load).
TOOLSETS: dict[str, Any] = {
    "files": FILES_TOOLS,
    "shell": SHELL_TOOLS,
    "notes": notes_tools,
}
DEFAULT_TOOLSETS: list[str] = ["files", "shell"]
