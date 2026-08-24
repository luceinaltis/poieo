"""Daemon configuration: which graphs run, on what trigger, against which binding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..binding import BindingSpec, load_binding
from ..errors import SpecError, describe_invalid
from ..graph import GraphSpec, load_document, load_graph
from ..memory import check_memory, read_memory
from ..tools import Isolation
from ..task import TaskSpec, expand, load_tasks, read_journal
from .triggers import TriggerSpec


class FlowSpec(BaseModel):
    """One logical workflow wired to a trigger and a binding."""

    model_config = ConfigDict(extra="forbid")

    name: str
    graph: str
    # Falls back to the daemon-level binding when omitted.
    binding: str | None = None
    trigger: TriggerSpec = Field(default_factory=TriggerSpec)
    enabled: bool = True

    # Static payload handed to every run.
    input: dict[str, Any] = Field(default_factory=dict)
    # Re-read before each run, so an external process can feed the flow.
    input_file: str | None = None
    # Carry the ending state of one run into the next -- the memory that makes
    # a looping flow accumulate instead of restarting from zero every time.
    carry_state: bool = False
    # Where this flow's commands may run. Absent means the host, as before.
    isolation: Isolation | None = None
    on_error: Literal["continue", "stop"] = "continue"

    @model_validator(mode="after")
    def _check_name(self) -> FlowSpec:
        if not self.name.strip():
            raise ValueError("flow name must not be empty")
        return self


class DaemonConfig(BaseModel):
    """The whole daemon: shared defaults plus a list of flows."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    # Where run logs are written.
    store: str = ".poieo"
    # Default binding for flows that do not name one.
    binding: str | None = None
    flows: list[FlowSpec] = Field(default_factory=list)
    # A folder of task files; each one expands into a flow. See poieo.task.
    tasks: str | None = None
    # How often the project sits down to learn from its run records
    # (a duration: "1d"). Absent means never. The tasks folder's memory/
    # stays the other half of the opt-in -- a config key alone must not
    # conjure the feature for a project that never chose it.
    learn: str | None = None

    source_path: Path | None = Field(default=None, exclude=True)
    # What each task-backed flow came from, by flow name. Filled by
    # load_config; anything a document puts here is discarded.
    task_graphs: dict[str, GraphSpec] = Field(default_factory=dict, exclude=True)
    tasks_by_flow: dict[str, TaskSpec] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="after")
    def _check_flows(self) -> DaemonConfig:
        names = [f.name for f in self.flows]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate flow names: {sorted(duplicates)}")
        for flow in self.flows:
            if not flow.binding and not self.binding:
                raise ValueError(
                    f"flow '{flow.name}' has no binding and the daemon declares no default"
                )
        if self.learn is not None:
            from .triggers import parse_duration

            parse_duration(self.learn)  # a bad interval fails at load, not at 3am
            if self.binding is None:
                raise ValueError(
                    "learn needs the daemon's default binding to read with"
                )
        return self

    # -- path helpers --------------------------------------------------------
    @property
    def base_dir(self) -> Path:
        return self.source_path.parent if self.source_path else Path.cwd()

    def resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to the config file, not the cwd."""
        path = Path(relative)
        return path if path.is_absolute() else (self.base_dir / path)

    def store_path(self) -> Path:
        return self.resolve_path(self.store)

    def binding_path(self, flow: FlowSpec) -> Path:
        target = flow.binding or self.binding
        assert target is not None  # guaranteed by _check_flows
        return self.resolve_path(target)


class LoadedFlow(BaseModel):
    """A flow with its graph and binding parsed and cross-checked."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    spec: FlowSpec
    graph: GraphSpec
    binding: BindingSpec
    binding_key: str

    def read_input(self, config: DaemonConfig) -> dict[str, Any]:
        payload = dict(self.spec.input)
        if self.spec.input_file:
            path = config.resolve_path(self.spec.input_file)
            if not path.exists():
                raise SpecError(f"flow '{self.spec.name}': input_file not found: {path}")
            try:
                text = path.read_text(encoding="utf-8")
                data = json.loads(text) if path.suffix == ".json" else load_document(path)
            except json.JSONDecodeError as exc:
                raise SpecError(f"flow '{self.spec.name}': {path}: {exc}") from exc
            if not isinstance(data, dict):
                raise SpecError(
                    f"flow '{self.spec.name}': {path} must contain a mapping"
                )
            payload.update(data)
        task = config.tasks_by_flow.get(self.spec.name)
        if task is not None:
            # Re-read every run: a note left at 8am is in effect at 9am.
            payload["journal"] = read_journal(task.journal_path())
            memory = read_memory(task.dir, task)
            if memory is not None:
                payload["memory"] = memory
        return payload


def load_config(path: str | Path) -> DaemonConfig:
    path = Path(path)
    data = load_document(path)
    try:
        config = DaemonConfig.model_validate(data)
    except Exception as exc:
        raise SpecError(
            f"{path}: invalid daemon config: "
            f"{describe_invalid(exc, tuple(DaemonConfig.model_fields))}"
        ) from exc
    config.source_path = path.resolve()
    _load_tasks(config)
    return config


def _load_tasks(config: DaemonConfig) -> None:
    """Expand the tasks folder into flows, if the config names one."""
    config.task_graphs = {}
    config.tasks_by_flow = {}
    if not config.tasks:
        return
    folder = config.resolve_path(config.tasks)
    if not folder.is_dir():
        raise SpecError(f"tasks folder does not exist: {folder}")
    # A typo in the project's memory fails here, where `poieo validate` and
    # the daemon's load can see it, never when a trigger fires at 3am.
    check_memory(folder)

    taken = {flow.name for flow in config.flows}
    # Two passes: a task's generated prompt names the tasks it may tell, and
    # that is not known until the whole folder has been read.
    tasks = load_tasks(folder)
    roster = [task.slug for task in tasks]
    for task in tasks:
        flow, graph = expand(task, roster=roster)
        if flow.name in taken:
            raise SpecError(
                f"task '{task.source_path}' is already a flow named '{flow.name}'"
            )
        taken.add(flow.name)
        if not flow.binding and not config.binding:
            raise SpecError(
                f"task '{task.slug}' names no binding and there is no default. "
                f"Add `binding: <file>` to the card, or to the daemon config."
            )
        config.flows.append(flow)
        config.tasks_by_flow[flow.name] = task
        if graph is not None:
            config.task_graphs[flow.name] = graph


def config_for_tasks_folder(folder: Path) -> DaemonConfig:
    """The config `poieo daemon <folder>` stands for: run the cards in it.

    Each card names its own binding, because there is no config file to hold
    a default. The store lands inside the folder, beside the journals, so
    everything about the cards travels with them -- and `poieo run` on one
    card follows the same rule.
    """
    folder = folder.resolve()
    config = DaemonConfig(store=str(folder / ".poieo"), tasks=str(folder))
    config.source_path = folder / "poieo.yaml"  # anchors relative paths
    _load_tasks(config)
    return config


def check_isolation(flows: list[FlowSpec]) -> None:
    """Docker present, answering, and every named image already here.

    The slowest preflight in the codebase -- a daemon ping plus one inspect per
    distinct image -- and the only one that reaches outside the process. What
    buys the cost is principle 5: a task whose image was pruned last week must
    not discover it at 3am.

    Flows that never asked are not merely skipped, they are not probed at all,
    so a machine with no docker pays nothing and fails nowhere. Neither are
    disabled flows: they are not going to run, and refusing to *list* one
    would be the check getting in the way of the fix.
    """
    wanted = [f for f in flows if f.isolation]
    if not wanted:
        return

    from ..tools import docker  # late: nothing imports it unless asked

    ok, reason = docker.docker_available()
    if not ok:
        names = ", ".join(sorted(f.name for f in wanted))
        raise SpecError(f"flow(s) {names} ask to run isolated, but {reason}")

    checked: set[str] = set()
    for flow in wanted:
        image = flow.isolation.image
        if image in checked:
            continue
        checked.add(image)
        if not docker.image_present(image):
            raise SpecError(
                f"flow '{flow.name}' runs isolated in '{image}', which is not on "
                f"this machine. Run: docker pull {image}"
            )


def load_flows(config: DaemonConfig, *, enabled_only: bool = True) -> list[LoadedFlow]:
    """Parse every flow's graph and binding, and verify roles resolve.

    Called at startup so a typo in any flow surfaces immediately rather than at
    3am when its cron finally fires.
    """
    from ..runtime.executor import preflight

    selected = [f for f in config.flows if f.enabled or not enabled_only]
    # Only what will actually run: `poieo flows` loads disabled flows to list
    # them, and a disabled flow whose image is gone must not block the listing.
    check_isolation([f for f in selected if f.enabled])

    graphs: dict[Path, GraphSpec] = {}
    bindings: dict[Path, BindingSpec] = {}
    loaded: list[LoadedFlow] = []

    for flow in selected:
        binding_path = config.binding_path(flow).resolve()
        if binding_path not in bindings:
            bindings[binding_path] = load_binding(binding_path)

        generated = config.task_graphs.get(flow.name)
        if generated is None:
            graph_path = config.resolve_path(flow.graph).resolve()
            if graph_path not in graphs:
                graphs[graph_path] = load_graph(graph_path)
            generated = graphs[graph_path]

        graph, binding = generated, bindings[binding_path]
        try:
            preflight(graph, binding)
        except Exception as exc:
            raise SpecError(f"flow '{flow.name}': {exc}") from exc

        loaded.append(
            LoadedFlow(
                spec=flow,
                graph=graph,
                binding=binding,
                binding_key=str(binding_path),
            )
        )
    return loaded
