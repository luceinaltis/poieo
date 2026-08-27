"""Daemon configuration: which graphs run, on what trigger, against which binding."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..binding import BindingSpec, load_binding
from ..errors import SpecError, describe_invalid
from ..graph import Branch, GraphSpec, load_document, load_graph
from ..layout import find_project_file
from ..memory import check_memory, keeps_memory
from ..project import ProjectSpec, load_project
from ..tools import Isolation
from ..task import TaskSpec, expand, load_tasks, task_payload
from .triggers import TriggerSpec

log = logging.getLogger("poieo.daemon")


class FlowSpec(BaseModel):
    """One logical workflow wired to a trigger and a binding."""

    model_config = ConfigDict(extra="forbid")

    name: str
    graph: str
    # Falls back to the daemon-level binding when omitted.
    binding: str | None = None
    trigger: TriggerSpec = Field(default_factory=TriggerSpec)
    enabled: bool = True

    # Where this flow's agent nodes work. Resolved against the config file, so
    # the graph can stay portable and say nothing about this machine.
    workdir: str | None = None

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

    # Which flow should work next, and on what condition. The router's own
    # when/to/label, one level up: first match wins, and `to: null` is the
    # router's own null -- matched, and deliberately no further.
    #
    # There is no `default`, because a finished run does not have to go
    # anywhere. Falling off the end means nothing happens, which is what
    # almost every flow does; a catch-all is a last branch reading `"true"`.
    then: list[Branch] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_name(self) -> FlowSpec:
        if not self.name.strip():
            raise ValueError("flow name must not be empty")
        return self


class DaemonConfig(ProjectSpec):
    """A project, plus the flows something intends to actually run.

    The paths -- store, binding, tasks, learn -- and how they resolve are the
    project's and live in :class:`~poieo.project.ProjectSpec`. One schema, so
    a key cannot mean one thing to `poieo run` and another to `poieo daemon`;
    what this adds is reading ``flows`` as flows rather than as whatever the
    document happened to say.

    (``learn``'s other half stays ``memory/longterm/`` beside the marker: a
    config key alone must not conjure the feature for a project that never
    chose it.)
    """

    flows: list[FlowSpec] = Field(default_factory=list)

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

            # Fails at load, not at 3am -- and a zero interval would spin
            # the loop without ever yielding, starving the whole daemon.
            if parse_duration(self.learn) <= 0:
                raise ValueError("learn must be a positive duration")
            if self.binding is None:
                raise ValueError(
                    "learn needs the daemon's default binding to read with"
                )
        return self

    # -- path helpers the flows need; the rest are the project's -------------
    def workdir_path(self, flow: FlowSpec) -> Path | None:
        # Resolved: this one is handed to a subprocess and shown in warnings,
        # so "examples/.." helps nobody.
        return self.resolve_path(flow.workdir).resolve() if flow.workdir else None

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
            payload.update(task_payload(task))
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
    check_handoffs(config)
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
    check_memory(config.base_dir)
    if config.learn is not None and not keeps_memory(config.base_dir):
        # Half an opt-in is the one way this feature dies quietly: the
        # key says learn, the folder says nothing is kept, and a person
        # waits a week for entries that were never going to arrive.
        # A warning, not a failure -- the folder is still the opt-in.
        log.warning(
            "%s says `learn: %s`, but %s does not exist, so nothing will be "
            "learned. Make that folder to keep a long memory.",
            config.source_path,
            config.learn,
            config.layout().longterm(),
        )

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

    The argument says *which cards to run*. It was never a claim about where
    the project begins, so a ``poieo.yaml`` above still answers that -- and
    when there is one, this is that project with its tasks folder swapped:
    same store, same binding, same memory. Joining a project halfway, taking
    its memory but not the model it reads with, is the kind of rule nobody
    can hold in their head.

    Without a marker there is nothing to join. The folder is the project,
    the history lands inside it, and each card names its own binding because
    there is no file to hold a default.
    """
    folder = folder.resolve()
    marker = find_project_file(folder)
    if marker is not None:
        project = load_project(marker)
        config = DaemonConfig(
            store=project.store,
            binding=project.binding,
            learn=project.learn,
            tasks=str(folder),
        )
        config.source_path = marker
    else:
        config = DaemonConfig(store=str(folder / "runs"), tasks=str(folder))
        config.source_path = folder / "poieo.yaml"  # anchors relative paths
    _load_tasks(config)
    check_handoffs(config)
    return config


def _first_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """One cycle in the handoff wiring, as the names on it, or None.

    One is enough: a person shown the first loop fixes it and runs again, and
    listing every loop in a tangle is a wall of text nobody reads.
    """
    open_: set[str] = set()
    done: set[str] = set()
    path: list[str] = []

    def walk(name: str) -> list[str] | None:
        open_.add(name)
        path.append(name)
        for target in edges.get(name, ()):
            if target in open_:
                return [*path[path.index(target) :], target]
            if target not in done:
                found = walk(target)
                if found is not None:
                    return found
        path.pop()
        open_.discard(name)
        done.add(name)
        return None

    for name in edges:
        if name not in done:
            found = walk(name)
            if found is not None:
                return found
    return None


def check_handoffs(config: DaemonConfig) -> None:
    """Every `then:` target exists and is not the sender; the rest is warnings.

    Not a validator on the config: a task card becomes a flow only after the
    tasks folder has been read, and a handoff is entitled to name one. So this
    runs once every flow is known, which is also the last moment before a
    trigger could fire.
    """
    known = {flow.name: flow for flow in config.flows}

    for flow in config.flows:
        for index, branch in enumerate(flow.then):
            if branch.to is None:
                continue  # matched, and deliberately no further
            if branch.to == flow.name:
                raise SpecError(
                    f"flow '{flow.name}' then[{index}] hands off to itself. A "
                    f"flow's own next run is what `loop` and `carry_state` are for."
                )
            target = known.get(branch.to)
            if target is None:
                # Say what was there. A handoff naming a flow that does not
                # exist is a typo far more often than it is a missing flow.
                roster = ", ".join(sorted(n for n in known if n != flow.name))
                raise SpecError(
                    f"flow '{flow.name}' then[{index}] hands off to unknown flow "
                    f"'{branch.to}'. There is: {roster or '(nothing else)'}"
                )
            if not target.enabled:
                log.warning(
                    "flow '%s' hands off to '%s', which is disabled: those "
                    "handoffs will be dropped. `enabled: false` is the off "
                    "switch, so this may well be deliberate.",
                    flow.name,
                    branch.to,
                )
        if flow.then and flow.trigger.type == "loop":
            log.warning(
                "flow '%s' hands off and runs on a `loop` trigger, so everything "
                "downstream inherits that pace. At most one handoff waits, and "
                "the rest are dropped.",
                flow.name,
            )

    cycle = _first_cycle(
        {f.name: [b.to for b in f.then if b.to is not None] for f in config.flows}
    )
    if cycle is not None:
        # A warning, not a failure: review -> fix -> review is a legitimate
        # feedback loop, and the chain-depth guard is what keeps it finite.
        log.warning(
            "handoffs form a cycle: %s. That is allowed -- the chain depth "
            "limit bounds it -- but check it is what you meant.",
            " -> ".join(cycle),
        )


def check_isolation(flows: list[FlowSpec]) -> None:
    """Docker present, answering, and every named image already here.

    The slowest preflight in the codebase -- a daemon ping plus one inspect per
    distinct image -- and the only one that reaches outside the process. What
    buys the cost is principle 5: a task whose image was pruned last week must
    not discover it at 3am.

    Flows that never asked are not merely skipped, they are not probed at all,
    so a machine with no docker pays nothing and fails nowhere.

    Whether *disabled* flows reach here is the caller's business, and
    load_flows keeps them out: they are not going to run, and refusing to
    *list* one would be the check getting in the way of the fix.
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
    from ..providers import check_credentials
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

        workdir = config.workdir_path(flow)
        if workdir is not None and not workdir.is_dir():
            raise SpecError(f"flow '{flow.name}': workdir does not exist: {workdir}")

        generated = config.task_graphs.get(flow.name)
        if generated is None:
            graph_path = config.resolve_path(flow.graph).resolve()
            if graph_path not in graphs:
                graphs[graph_path] = load_graph(graph_path)
            generated = graphs[graph_path]

        graph, binding = generated, bindings[binding_path]
        try:
            preflight(graph, binding, workdir=workdir)
            # A key the machine does not have is a misconfiguration, and it
            # reads the environment rather than a server -- so it belongs
            # here, beside the other things that must not wait until 3am.
            # Enabled flows only, for the reason check_isolation gives: a
            # flow that is not going to run must still be listable, or the
            # check gets in the way of the fix.
            if flow.enabled:
                check_credentials(binding, graph.roles())
        except Exception as exc:
            raise SpecError(f"flow '{flow.name}': {exc}") from exc

        # A node that names a role the binding never heard of still runs -- on
        # whatever `default` is, which in a cloud binding is the biggest model
        # in the file. `role: classifer` is a one-letter typo away from the
        # cheapest, and nothing has ever said so. A warning rather than a
        # refusal: falling back is what a default is for, and a binding that
        # declares no roles at all is a legitimate way to run a graph.
        #
        # The graph's own `default_role` is excluded -- a node that named no
        # role asking for the binding's default is the arrangement working.
        #
        # And only a binding that declares roles at all is asked: one that
        # declares none is saying "one model for everything", which every mock
        # binding does, and every role legitimately falls through it. The
        # suspicious case is a binding that has `classifier` and `writer` and
        # is handed a third name.
        strangers = (
            binding.undeclared(graph.roles() - {graph.default_role})
            if binding.roles
            else []
        )
        if strangers:
            log.warning(
                "flow '%s': graph '%s' asks for role(s) %s, which binding '%s' "
                "does not declare -- they will run on its default (%s). Check "
                "for a typo.",
                flow.name,
                graph.name,
                ", ".join(strangers),
                binding.name,
                binding.default.model or "no model named",
            )

        loaded.append(
            LoadedFlow(
                spec=flow,
                graph=graph,
                binding=binding,
                binding_key=str(binding_path),
            )
        )
    return loaded
