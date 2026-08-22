"""A task is a name, a folder, and a prompt -- the smallest thing that runs.

Everything else has a default. A task is *sugar*: at load time it expands into
a flow plus a one-node graph indistinguishable from hand-written ones, so
nothing downstream of the loader knows tasks exist. The expansion is visible
(``poieo show``) and reversible (``poieo eject``), which is what keeps the
short form from becoming a second, hidden configuration format.

Paths inside a task file resolve against the task file itself, so a task is
self-contained whether the daemon loads it or the CLI does.

Spec: docs/superpowers/specs/2026-08-22-task-cards-design.md
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import SpecError
from .graph import GraphSpec, NodeSpec, OutputSpec, load_document
from .tools import Isolation

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .daemon.config import FlowSpec

log = logging.getLogger("poieo.task")

DEFAULT_EVERY = "1h"
DEFAULT_TOOLS = ["files", "shell"]
DEFAULT_MAX_TURNS = 40

# How many journal entries reach the prompt. The file keeps everything; this
# only bounds what the model is asked to hold in mind.
JOURNAL_LIMIT = 20
# A single entry is one line, so a chatty model cannot bury the rest.
JOURNAL_WIDTH = 300


def system_block(task: TaskSpec) -> str:
    """The generated node's system prompt. User-visible, so it is fixed here.

    The journal arrives as run input rather than baked in, because it is
    re-read before every run -- a note written at 8am is in effect at 9am.
    """
    return (
        f"You are working on {task.name}, in {task.folder_path()}.\n\n"
        "What you have already done, and what the user has told you:\n"
        "{{ input.journal }}\n\n"
        "Finish by saying in one line what you did. If there was nothing worth\n"
        "doing, say that in one line instead."
    )


# Keys that describe the single generated node, and therefore have nowhere to
# go once the task names a graph of its own.
_NODE_KEYS = ("prompt", "role", "tools", "max_turns")


class TaskSpec(BaseModel):
    """One card: what to do, where, and how often."""

    model_config = ConfigDict(extra="forbid")

    name: str
    folder: str
    # Exactly one of these. `graph` is what `poieo eject` writes.
    prompt: str | None = None
    graph: str | None = None

    # Schedule sugar: a duration, the word "loop", or a cron expression.
    every: str | float | None = None
    at: str | None = None

    role: str | None = None
    tools: list[str] | None = None
    max_turns: int = Field(default=DEFAULT_MAX_TURNS, ge=1, le=200)
    enabled: bool = True
    binding: str | None = None
    # Where this task's commands may run. Absent means the host, as before.
    # Not a node key: it describes the task, so `poieo eject` keeps it.
    isolation: Isolation | None = None

    # Populated by load_task; not part of the authored document.
    source_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _check(self) -> TaskSpec:
        if not self.name.strip():
            raise ValueError("task name must not be empty")
        if self.prompt and self.graph:
            raise ValueError("a task takes a prompt or a graph, not both")
        if not self.prompt and not self.graph:
            raise ValueError("a task needs a prompt (or a graph, once ejected)")
        if self.graph:
            named = [k for k in _NODE_KEYS if getattr(self, k) not in (None, DEFAULT_MAX_TURNS)]
            if named:
                raise ValueError(
                    f"{', '.join(named)} belong in the graph once a task names one"
                )
        if self.every is not None and self.at is not None:
            raise ValueError("a task is scheduled by 'every' or 'at', not both")
        return self

    @property
    def slug(self) -> str:
        """The task's identity: its filename, never its rewritable title."""
        if self.source_path is None:
            raise SpecError("task has no source path; load it with load_task()")
        return self.source_path.stem

    @property
    def dir(self) -> Path:
        if self.source_path is None:
            raise SpecError("task has no source path; load it with load_task()")
        return self.source_path.parent

    def resolve(self, relative: str) -> Path:
        """Resolve a path written in the task file, relative to the file."""
        path = Path(relative).expanduser()
        return (path if path.is_absolute() else self.dir / path).resolve()

    def folder_path(self) -> Path:
        return self.resolve(self.folder)

    def journal_path(self) -> Path:
        """Where this task remembers: beside it, under the same name."""
        return self.dir / f"{self.slug}.md"


def load_task(path: str | Path) -> TaskSpec:
    """Load and fully validate a task file."""
    path = Path(path)
    data = load_document(path)
    try:
        task = TaskSpec.model_validate(data)
    except Exception as exc:
        raise SpecError(f"{path}: invalid task: {exc}") from exc
    task.source_path = path
    folder = task.folder_path()
    if not folder.is_dir():
        raise SpecError(f"{path}: folder does not exist: {folder}")
    return task


def is_task_document(data: dict[str, Any]) -> bool:
    """A task has a folder and no nodes; a graph is the other way round."""
    return "folder" in data and "nodes" not in data


def is_task_file(path: str | Path) -> bool:
    try:
        return is_task_document(load_document(path))
    except SpecError:
        return False


def _trigger(task: TaskSpec) -> dict[str, Any]:
    if task.at is not None:
        return {"type": "cron", "expression": task.at}
    every = DEFAULT_EVERY if task.every is None else task.every
    if isinstance(every, str) and every.strip().lower() == "loop":
        return {"type": "loop"}
    return {"type": "interval", "every": every}


def build_graph(task: TaskSpec) -> GraphSpec:
    """The one-node graph a prompt-shaped task stands for."""
    return GraphSpec(
        name=task.slug,
        description=task.name,
        entry="work",
        nodes=[
            NodeSpec(
                id="work",
                type="agent",
                role=task.role,
                workdir=str(task.folder_path()),
                tools=task.tools or list(DEFAULT_TOOLS),
                max_turns=task.max_turns,
                system=system_block(task),
                prompt=task.prompt,
                output=OutputSpec(as_="summary"),
            )
        ],
    )


def expand(task: TaskSpec) -> tuple[FlowSpec, GraphSpec | None]:
    """Desugar a task into the flow and graph the rest of poieo understands.

    The graph is None when the task names one of its own; the flow then points
    at that file and is loaded like any other.
    """
    from .daemon.config import FlowSpec  # late import: config imports this module

    graph = None if task.graph else build_graph(task)
    flow = FlowSpec(
        name=task.slug,
        # With no graph file of its own, the flow points at the task that stands
        # in for one. Only load_flows reads this, and it prefers the generated
        # graph it was handed alongside.
        graph=str(task.resolve(task.graph) if task.graph else task.source_path),
        binding=task.binding,
        trigger=_trigger(task),
        enabled=task.enabled,
        isolation=task.isolation,
        # A task is a standing job, so what it learned last night is in scope
        # tonight. Hand-written flows still opt in.
        carry_state=True,
    )
    return flow, graph


def load_tasks(folder: str | Path) -> list[TaskSpec]:
    """Every task file in a folder, in a stable order."""
    folder = Path(folder)
    suffixes = {".yaml", ".yml", ".json"}
    files = sorted(
        p for p in folder.iterdir() if p.suffix.lower() in suffixes and not p.name.startswith(".")
    )
    return [load_task(p) for p in files]


# -- the journal -------------------------------------------------------------
#
# One markdown file per task, appended to and never rewritten, so a line the
# user types by hand works exactly like a line poieo wrote.


def read_journal(path: Path, limit: int = JOURNAL_LIMIT) -> str:
    """The tail of a task's journal, as it goes into the prompt.

    Read as text, not parsed: that is what makes hand-written lines work.
    """
    try:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        # Forgetting beats failing, but say so: a task that cannot read its
        # journal repeats itself silently.
        log.warning("could not read the journal %s: %s", path, exc)
        raw = ""
    lines = [
        line.rstrip()
        for line in raw.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not lines:
        return "nothing yet"
    if len(lines) > limit:
        return "\n".join(["(earlier entries omitted)", *lines[-limit:]])
    return "\n".join(lines)


def append_journal(
    path: Path,
    kind: str,
    text: str,
    *,
    title: str | None = None,
    when: datetime | None = None,
) -> None:
    """Add one line. ``kind`` is did / nothing / failed / you."""
    one_line = " ".join(str(text).split()) or "(nothing said)"
    if len(one_line) > JOURNAL_WIDTH:
        one_line = one_line[: JOURNAL_WIDTH - 3] + "..."
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")

    opening = "" if path.exists() else f"# {title or path.stem}\n\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{opening}- {stamp} · {kind:<8}{one_line}\n")
