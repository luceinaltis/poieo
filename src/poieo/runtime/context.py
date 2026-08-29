"""Per-run state and the scope expressions see."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from ..binding import BindingSpec
from ..expr import wrap
from ..graph import GraphSpec
from ..providers import ProviderPool, Usage
from ..store import Event, RunStore
from ..tools import ToolContext


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


@dataclass
class RunContext:
    """Everything a node needs, and everything a run accumulates."""

    graph: GraphSpec
    binding: BindingSpec
    pool: ProviderPool
    store: RunStore
    run_id: str = field(default_factory=new_run_id)
    task: str = "adhoc"
    trigger: str = "manual"
    # Payload supplied by the trigger or the CLI.
    input: dict[str, Any] = field(default_factory=dict)
    # Survives across iterations when a loop trigger carries state.
    state: dict[str, Any] = field(default_factory=dict)
    # Which pass of a looping task this is.
    iteration: int = 0
    # Set by execute(); agent loops poll it between turns.
    cancel: asyncio.Event | None = None
    # Where agent nodes work unless they name a directory of their own.
    workdir: Path | None = None
    # What those tools may reach, and who they may tell. The runtime carries
    # it and never opens it -- which is how it stays unaware that containers,
    # or journals, exist at all.
    tool_context: ToolContext | None = None

    outputs: dict[str, Any] = field(default_factory=dict)
    aliases: dict[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    path: list[str] = field(default_factory=list)
    # Monotonic, not the wall clock: a run that starts at 2am may cross an NTP
    # correction or a daylight-saving change, and a guard set on how long it
    # has been going must not jump when it does.
    #
    # `perf_counter` and not `monotonic`, which on Windows ticks every 15.6ms
    # -- long enough that a run reads as having taken exactly no time at all
    # for its first few steps.
    started: float = field(default_factory=time.perf_counter)

    def scope(self) -> dict[str, Any]:
        """Names visible to prompt templates and router conditions."""
        scope: dict[str, Any] = {
            "input": wrap(self.input),
            "state": wrap(self.state),
            "nodes": wrap(self.outputs),
            "run": wrap(
                {
                    "id": self.run_id,
                    "task": self.task,
                    "trigger": self.trigger,
                    "iteration": self.iteration,
                    "path": list(self.path),
                    # What it has cost so far, and how long it has been at it.
                    # Both are here so a router can stop a run that is still
                    # going: `max_steps` bounds the walk, but one agent node
                    # with tools is a single step however many turns it takes
                    # inside, so it bounds neither the money nor the night.
                    #
                    # Tokens rather than an amount of money: nothing in poieo
                    # knows what a model charges, and a price table checked in
                    # here would be wrong the week after it was written.
                    "usage": self.usage.as_dict(),
                    "elapsed": time.perf_counter() - self.started,
                }
            ),
        }
        # Output aliases sit at the top level so a graph reads `{{ category }}`.
        for name, value in self.aliases.items():
            scope.setdefault(name, wrap(value))
        return scope

    def record_output(self, node_id: str, value: Any, alias: str | None) -> None:
        self.outputs[node_id] = value
        if alias:
            self.aliases[alias] = value

    def emit(self, type_: str, node_id: str | None = None, **data: Any) -> None:
        self.store.append(
            Event(run_id=self.run_id, type=type_, node_id=node_id, data=data)
        )


@dataclass(slots=True)
class NodeResult:
    """What a node hands back to the executor."""

    node_id: str
    next_node: str | None
    output: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    run_id: str
    task: str
    graph: str
    status: str  # completed | failed | aborted
    started_at: str
    finished_at: str
    steps: int
    path: list[str]
    usage: dict[str, int]
    outputs: dict[str, Any]
    state: dict[str, Any]
    error: str | None = None
    # The failure in the user's words ({slug, said, fix}), when one of the
    # known causes matched. The raw error above is always kept beside it.
    cause: dict[str, Any] | None = None
    iteration: int = 0
    # What actually fired this run -- "cron 0 2 * * *", "run now", "after
    # chores (changed)". Not the task's configured schedule, which may well not
    # be what rang: a run-now and a handoff both happen outside it.
    trigger: str = ""
    # Which project's task this was. One daemon can run several, and then
    # "which task ran" stops being enough to say whose night it was -- a
    # record that cannot say cannot be filtered or labelled later either.
    project: str = ""
    # Set after the run by the daemon when the task keeps a private copy.
    change: dict[str, Any] | None = None

    def said(self, fallback: str = "") -> str:
        """What the model said last: the last node on the path that produced text.

        One reading, shared by the journal, the run record, the change's commit
        message and the board -- so those four can never tell four stories
        about one run. It lives here because `path` and `outputs` do.
        """
        for node_id in reversed(self.path):
            value = self.outputs.get(node_id)
            if isinstance(value, str) and value.strip():
                return value
        return fallback

    def summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "run_id": self.run_id,
            "task": self.task,
            "project": self.project,
            "graph": self.graph,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": self.steps,
            "iteration": self.iteration,
            "trigger": self.trigger,
            "usage": self.usage,
            "error": self.error,
            # The run's own account of itself, whether or not it changed a
            # file. Without it a list of runs that touched nothing reads as
            # ten identical rows of "2 steps", which is the graph's shape and
            # not news about any of them.
            "said": self.said(),
        }
        # Absent, not null: a run that changed nothing has nothing to review,
        # and the difference matters to the card that reads this.
        if self.change is not None:
            summary["change"] = self.change
        if self.cause is not None:
            summary["cause"] = self.cause
        return summary
