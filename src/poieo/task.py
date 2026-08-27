"""A task is a name, a folder, and a prompt -- the smallest thing that runs.

Everything else has a default. A task is *sugar*: at load time it expands into
a flow plus a one-node graph indistinguishable from hand-written ones, so
nothing downstream of the loader knows tasks exist. The expansion is visible
(``poieo show``) and reversible (``poieo eject``), which is what keeps the
short form from becoming a second, hidden configuration format.

Paths inside a task file resolve against the task file itself, so a task is
self-contained whether the daemon loads it or the CLI does.

Design: docs/tasks.md
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import SpecError, describe_invalid
from .graph import GraphSpec, NodeSpec, OutputSpec, load_document
from .layout import layout_for
from .memory import read_memory, write_result
from .tools import DEFAULT_TOOLSETS, Isolation

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .daemon.config import FlowSpec

log = logging.getLogger("poieo.task")

DEFAULT_EVERY = "1h"
DEFAULT_MAX_TURNS = 40

# How many journal entries reach the prompt. The file keeps everything; this
# only bounds what the model is asked to hold in mind.
JOURNAL_LIMIT = 20
# A single entry is one line, so a chatty model cannot bury the rest.
JOURNAL_WIDTH = 300


def system_block(task: TaskSpec, roster: list[str] | None = None) -> str:
    """The generated node's system prompt. User-visible, so it is fixed here.

    The journal arrives as run input rather than baked in, because it is
    re-read before every run -- a note written at 8am is in effect at 9am.
    """
    return (
        f"You are working on {task.name}, in {task.folder_path()}.\n\n"
        + _memory_section(task)
        + "What you have already done, and what the user has told you:\n"
        "{{ input.journal }}\n\n"
        "Finish by saying in one line what you did. If there was nothing worth\n"
        "doing, say that in one line instead."
        + _roster_block(task, roster)
    )


def _memory_section(task: TaskSpec) -> str:
    """The project's memory, for a project that keeps one.

    Gated on content, so a project that never made a memory sees no trace of
    the feature -- not even an empty header.
    """
    # preview: `tasks`, `show` and the daemon's load all build a prompt, and
    # none of them is a run, so the gate must leave no machinery behind.
    if read_memory(task.dir, task, preview=True) is None:
        return ""
    return "{{ input.memory }}\n\n"


def _roster_block(task: TaskSpec, roster: list[str] | None) -> str:
    """Who this task may leave a note for.

    A model cannot address a task it does not know exists, so one that did not
    ask for the notes toolset is told nothing at all.
    """
    if "notes" not in (task.tools or DEFAULT_TOOLSETS):
        return ""
    others = [name for name in (roster or []) if name != task.slug]
    if not others:
        return ""
    return (
        "\n\nOther tasks you can leave a note for: "
        + ", ".join(others)
        + ".\nThey read it on their next run, not now, so do not wait for a reply."
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
        # Under memory/, not beside the card: a card is edited by hand, a
        # journal grows every night, and together they made the folder of
        # definitions go dirty in git on every run.
        return layout_for(self.dir).journal(self.slug)


def load_task(path: str | Path) -> TaskSpec:
    """Load and fully validate a task file."""
    path = Path(path)
    data = load_document(path)
    try:
        task = TaskSpec.model_validate(data)
    except Exception as exc:
        raise SpecError(
            f"{path}: invalid task: "
            f"{describe_invalid(exc, tuple(TaskSpec.model_fields))}"
        ) from exc
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


def build_graph(task: TaskSpec, roster: list[str] | None = None) -> GraphSpec:
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
                # No workdir on the node, for the reason
                # examples/tasks/agent-task.graph.yaml gives for not naming
                # one: a path is physical and a graph is not. Pinning the real
                # folder here sent the model there even on a night when the
                # task had a private copy of it open -- which is every night.
                tools=task.tools or list(DEFAULT_TOOLSETS),
                max_turns=task.max_turns,
                system=system_block(task, roster),
                prompt=task.prompt,
                output=OutputSpec(as_="summary"),
            )
        ],
    )


def expand(
    task: TaskSpec, roster: list[str] | None = None
) -> tuple[FlowSpec, GraphSpec | None]:
    """Desugar a task into the flow and graph the rest of poieo understands.

    The graph is None when the task names one of its own; the flow then points
    at that file and is loaded like any other.
    """
    from pydantic import ValidationError

    from .daemon.config import FlowSpec  # late import: config imports this module

    graph = None if task.graph else build_graph(task, roster)
    try:
        flow = FlowSpec(
            name=task.slug,
            # With no graph file, the flow points at the card standing in for
            # one; load_flows prefers the generated graph handed alongside.
            graph=str(task.resolve(task.graph) if task.graph else task.source_path),
            binding=task.binding,
            trigger=_trigger(task),
            enabled=task.enabled,
            isolation=task.isolation,
            # The folder is what turns the private copy on, and a card had no
            # way to say it: `folder` reached the generated node and stopped
            # there, so a card's work went straight into the user's own files.
            workdir=str(task.folder_path()),
            # A task is a standing job, so what it learned last night is in
            # scope tonight. Hand-written flows still opt in.
            carry_state=True,
        )
    except (ValidationError, SpecError) as exc:
        # Ten cards in a folder: the message has to say which one.
        raise SpecError(f"task '{task.slug}': {describe_invalid(exc)}") from exc
    return flow, graph


def load_tasks(folder: str | Path) -> list[TaskSpec]:
    """Every card in a folder, in a stable order.

    Graphs live here too, so the document says which is which: a card has a
    folder, a graph has nodes. Deliberately *not* sorted by trying to parse
    each as a card and taking silence for a no -- that turns a typo into a
    task that quietly stops running.
    """
    folder = Path(folder)
    suffixes = {".yaml", ".yml", ".json"}
    files = sorted(
        p for p in folder.iterdir() if p.suffix.lower() in suffixes and not p.name.startswith(".")
    )
    tasks = []
    for path in files:
        data = load_document(path)
        if is_task_document(data):
            tasks.append(load_task(path))
        elif "nodes" in data and "folder" not in data:
            continue  # a graph: a card names it, or a flow in poieo.yaml does
        else:
            # Neither shape, or both at once -- a card that grew a `nodes:` key
            # answers to no rule, and skipping it would be that silent
            # disappearance.
            raise SpecError(
                f"{path}: this is neither a card (`folder:`, no `nodes:`) "
                f"nor a graph (`nodes:`, no `folder:`)"
            )
    return tasks


def record_run(task: TaskSpec, result: Any) -> None:
    """Add one run to the task's journal, so the next one can read it.

    **Every runner of a task must land here** -- the daemon's and the CLI's
    one-shot alike. Reading splits at the task's own last entry, so a run that
    writes none leaves every note marked new forever.

    ``result`` is duck-typed (status / path / outputs / error) so this module
    does not grow a dependency on the runtime.
    """
    # Both writes swallow their own failures, so neither can cost the other.
    write_result(task, result)
    if result.status == "completed":
        kind, text = "did", closing_line(result)
    else:
        kind = "failed"
        cause = getattr(result, "cause", None)
        # A sentence and an action beat an exception repr for the next reader;
        # the repr stays in the run record.
        if cause:
            text = f"{cause['said']} -- {cause['fix']}"
        else:
            text = result.error or result.status
    try:
        append_journal(task.journal_path(), kind, text, title=task.name)
    except OSError as exc:
        # Memory is not worth killing a night's work over.
        log.warning("task '%s': could not write the journal: %s", task.slug, exc)


def closing_line(result: Any, fallback: str = "(said nothing)") -> str:
    """What the model said last: the last node on the path that produced text.

    One reading, shared by the journal, the run record and the change's commit
    message, so those three can never tell three stories about one run.
    """
    for node_id in reversed(result.path):
        value = result.outputs.get(node_id)
        if isinstance(value, str) and value.strip():
            return value
    return fallback


# -- the journal -------------------------------------------------------------
#
# One markdown file per task, appended to and never rewritten, so a line the
# user types by hand works exactly like a line poieo wrote.


# What a task writes at the end of its own run; the last such line is the
# bookmark. "nothing" is reserved: no writer produces it yet.
OWN_KINDS = ("did", "nothing")
# One entry looks like: `- <date> <time> {sep} <kind padded> <text>`.
PREFIX = "- "
SEPARATOR = " · "
NEW_HEADER = "New since you last worked:"
OLD_HEADER = "What you did before that:"


def _entries(path: Path) -> list[str]:
    """Every journal line, as text -- never parsed."""
    try:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        # Forgetting beats failing, but say so: a task that cannot read its
        # journal repeats itself silently.
        log.warning("could not read the journal %s: %s", path, exc)
        raw = ""
    return [
        line.rstrip()
        for line in raw.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _is_own_entry(line: str) -> bool:
    """Is this line the task writing about its own run?

    Read by structure, not by searching the text: a forged bookmark would mark
    real notes as read, silently.
    """
    head, sep, rest = line.partition(SEPARATOR)
    if not sep or not head.startswith(PREFIX):
        return False
    return rest.split(' ', 1)[0] in OWN_KINDS


def _bookmark(lines: list[str]) -> int:
    """Index just past the task's own last completed run, or 0.

    A failed run is deliberately not a bookmark: repeating a note is
    recoverable where losing one is not.
    """
    for i in range(len(lines) - 1, -1, -1):
        if _is_own_entry(lines[i]):
            return i + 1
    return 0


def task_payload(task: TaskSpec) -> dict[str, Any]:
    """What a card's generated graph is given, beyond the user's own input.

    One statement of the rule, shared by the two runners -- `poieo run` and the
    daemon -- which have to agree. Re-read on every call, never cached: a note
    left at 8am is in effect at 9am.
    """
    payload: dict[str, Any] = {"journal": read_journal(task.journal_path())}
    memory = read_memory(task.dir, task)
    if memory is not None:
        payload["memory"] = memory
    return payload


def read_journal(path: Path, limit: int = JOURNAL_LIMIT) -> str:
    """The journal as a prompt sees it: what is new, then what came before.

    Cut at the task's own last entry, so what is new is chosen by *position*:
    no quantity of notes can push another out before it has been seen once.
    Only the half allowed to age out is bounded.
    """
    lines = _entries(path)
    if not lines:
        return "nothing yet"

    at = _bookmark(lines)
    fresh, history = lines[at:], lines[:at]

    if not fresh:
        head = "Nothing new since you last worked."
    else:
        shown, waiting = fresh[:limit], max(0, len(fresh) - limit)
        # Oldest first, always: showing the newest would strand the oldest
        # forever, since the bookmark only moves as far as what was shown.
        head = "\n".join([NEW_HEADER, *shown])
        if waiting:
            head += f"\n({waiting} more waiting; you will see them next time)"

    if not history:
        return head
    tail = history[-limit:]
    omitted = ["(earlier entries omitted)"] if len(history) > limit else []
    return "\n".join([head, "", OLD_HEADER, *omitted, *tail])


def append_journal(
    path: Path,
    kind: str,
    text: str,
    *,
    title: str | None = None,
    when: datetime | None = None,
) -> None:
    """Add one line.

    ``kind`` is what wrote it: ``did`` or ``failed`` for a run of this task,
    ``you`` for the user, ``task`` for a note from a sibling. Only the first
    two count as the task's own; see OWN_KINDS.
    """
    one_line = " ".join(str(text).split()) or "(nothing said)"
    if len(one_line) > JOURNAL_WIDTH:
        one_line = one_line[: JOURNAL_WIDTH - 3] + "..."
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")

    opening = "" if path.exists() else f"# {title or path.stem}\n\n"
    # `memory/shortterm/` need not exist yet: the first line a task writes is
    # what makes it.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{opening}- {stamp} · {kind:<8}{one_line}\n")
