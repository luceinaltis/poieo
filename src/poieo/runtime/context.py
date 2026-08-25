"""Per-run state and the scope expressions see."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from ..binding import BindingSpec
from ..expr import unwrap, wrap
from ..graph import GraphSpec
from ..providers import ProviderPool, Usage
from ..store import Event, RunStore
from ..tools import Hands


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
    flow: str = "adhoc"
    trigger: str = "manual"
    # Payload supplied by the trigger or the CLI.
    input: dict[str, Any] = field(default_factory=dict)
    # Survives across iterations when a loop trigger carries state.
    state: dict[str, Any] = field(default_factory=dict)
    # Which pass of a looping flow this is.
    iteration: int = 0
    # Set by execute(); agent loops poll it between turns.
    cancel: asyncio.Event | None = None
    # Where agent nodes work unless they name a directory of their own.
    workdir: Path | None = None
    # What those tools may reach, and who they may tell. The runtime carries
    # it and never opens it -- which is how it stays unaware that containers,
    # or journals, exist at all.
    hands: Hands | None = None

    outputs: dict[str, Any] = field(default_factory=dict)
    aliases: dict[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    path: list[str] = field(default_factory=list)

    def scope(self) -> dict[str, Any]:
        """Names visible to prompt templates and router conditions."""
        scope: dict[str, Any] = {
            "input": wrap(self.input),
            "state": wrap(self.state),
            "nodes": wrap(self.outputs),
            "run": wrap(
                {
                    "id": self.run_id,
                    "flow": self.flow,
                    "trigger": self.trigger,
                    "iteration": self.iteration,
                    "path": list(self.path),
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

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "flow": self.flow,
            "iteration": self.iteration,
            "state": unwrap(self.state),
            "outputs": unwrap(self.outputs),
            "aliases": unwrap(self.aliases),
        }


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
    flow: str
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
    iteration: int = 0
    # Set after the run by the daemon when the flow keeps a private copy.
    change: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "run_id": self.run_id,
            "flow": self.flow,
            "graph": self.graph,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": self.steps,
            "iteration": self.iteration,
            "usage": self.usage,
            "error": self.error,
        }
        # Absent, not null: a run that changed nothing has nothing to review,
        # and the difference matters to the card that reads this.
        if self.change is not None:
            summary["change"] = self.change
        return summary
