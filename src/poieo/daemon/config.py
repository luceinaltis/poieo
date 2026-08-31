"""Daemon configuration: which graphs run, on what trigger, against which binding."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from ..binding import BindingSpec, load_binding
from ..card import CardSpec, card_payload, expand, load_cards
from ..errors import SpecError
from ..graph import Branch, GraphSpec, load_document, load_graph, load_spec
from ..layout import find_project_file
from ..memory import check_memory, keeps_memory
from ..project import ProjectSpec, load_project
from ..tools import Isolation
from .triggers import TriggerSpec

log = logging.getLogger("poieo.daemon")


class TaskSpec(BaseModel):
    """One logical workflow wired to a trigger and a binding."""

    model_config = ConfigDict(extra="forbid")

    name: str
    graph: str
    # Falls back to the daemon-level binding when omitted.
    binding: str | None = None
    trigger: TriggerSpec = Field(default_factory=TriggerSpec)
    enabled: bool = True

    # Where this task's agent nodes work. Resolved against the config file, so
    # the graph can stay portable and say nothing about this machine.
    workdir: str | None = None

    # Static payload handed to every run.
    input: dict[str, Any] = Field(default_factory=dict)
    # Re-read before each run, so an external process can feed the task.
    input_file: str | None = None
    # Carry the ending state of one run into the next -- the memory that makes
    # a looping task accumulate instead of restarting from zero every time.
    carry_state: bool = False
    # Where this task's commands may run. Absent means the host, as before.
    isolation: Isolation | None = None
    on_error: Literal["continue", "stop"] = "continue"

    # Which task should work next: the router's own when/to/label, one level
    # up. First match wins, and `to: null` means matched-and-no-further. No
    # `default`, because a finished run does not have to go anywhere; a
    # catch-all is a last branch reading `"true"`.
    then: list[Branch] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_name(self) -> TaskSpec:
        if not self.name.strip():
            raise ValueError("task name must not be empty")
        return self


class DaemonConfig(ProjectSpec):
    """A project, plus the tasks something intends to actually run.

    The paths live in :class:`~poieo.project.ProjectSpec`; what this adds is
    reading ``tasks`` as tasks. One schema, so a key cannot mean one thing to
    `poieo run` and another to `poieo daemon`.
    """

    # Not a document key -- `tasks:` in the file names the folder, and this is
    # what was found in it. A property rather than a field so the two cannot
    # collide over one word, which is the thing this whole naming is for.
    _tasks: list[TaskSpec] = PrivateAttr(default_factory=list)

    @property
    def tasks(self) -> list[TaskSpec]:
        """The jobs this project runs, once the cards have been read."""
        return self._tasks

    @tasks.setter
    def tasks(self, value: list[TaskSpec]) -> None:
        # `poieo daemon --task one` narrows the roster to one; nothing else
        # replaces it wholesale.
        self._tasks = value

    # What each task-backed task came from, by task name. Filled by
    # load_config; anything a document puts here is discarded.
    card_graphs: dict[str, GraphSpec] = Field(default_factory=dict, exclude=True)
    cards_by_task: dict[str, CardSpec] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _flows_are_files_now(cls, data: Any) -> Any:
        """`flows:` was a second way to say what a card says.

        One list in one shared file, against one file per job in a folder: the
        list is the worse of the two for a board that creates jobs, for a diff
        that should show only the job that changed, and for a reader who had to
        learn two spellings of every key. Refused by name rather than by
        "not a setting here", which would not say where the work went.
        """
        if isinstance(data, dict) and "flows" in data:
            raise ValueError(
                "`flows:` is gone -- a job is one file in the tasks folder. "
                "Give each entry its own card there, and point `tasks:` at it"
            )
        return data

    @model_validator(mode="after")
    def _check_flows(self) -> DaemonConfig:
        names = [f.name for f in self.tasks]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate task names: {sorted(duplicates)}")
        for task in self.tasks:
            if not task.binding and not self.binding:
                raise ValueError(f"task '{task.name}' has no binding and the daemon declares no default")
        if self.learn is not None:
            from .triggers import parse_duration

            # Fails at load, not at 3am -- and a zero interval would spin
            # the loop without ever yielding, starving the whole daemon.
            if parse_duration(self.learn) <= 0:
                raise ValueError("learn must be a positive duration")
            if self.binding is None:
                raise ValueError("learn needs the daemon's default binding to read with")
        return self

    # -- path helpers the tasks need; the rest are the project's -------------
    def workdir_path(self, task: TaskSpec) -> Path | None:
        # Resolved: this one is handed to a subprocess and shown in warnings,
        # so "examples/.." helps nobody.
        return self.resolve_path(task.workdir).resolve() if task.workdir else None

    def binding_path(self, task: TaskSpec) -> Path:
        target = task.binding or self.binding
        assert target is not None  # guaranteed by _check_flows
        return self.resolve_path(target)

    def default_binding_path(self) -> Path | None:
        """The file this project's tasks fall back to, or None if it names one
        for none of them.

        Resolved, because that is the spelling `LoadedTask.binding_key` is
        built from and a caller comparing an unresolved path against one would
        match nothing at all.
        """
        return self.resolve_path(self.binding).resolve() if self.binding else None


class LoadedTask(BaseModel):
    """A task with its graph and binding parsed and cross-checked."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    spec: TaskSpec
    graph: GraphSpec
    binding: BindingSpec
    binding_key: str

    def read_input(self, config: DaemonConfig) -> dict[str, Any]:
        payload = dict(self.spec.input)
        if self.spec.input_file:
            path = config.resolve_path(self.spec.input_file)
            if not path.exists():
                raise SpecError(f"task '{self.spec.name}': input_file not found: {path}")
            try:
                text = path.read_text(encoding="utf-8")
                data = json.loads(text) if path.suffix == ".json" else load_document(path)
            except json.JSONDecodeError as exc:
                raise SpecError(f"task '{self.spec.name}': {path}: {exc}") from exc
            if not isinstance(data, dict):
                raise SpecError(f"task '{self.spec.name}': {path} must contain a mapping")
            payload.update(data)
        task = config.cards_by_task.get(self.spec.name)
        if task is not None:
            payload.update(card_payload(task))
        return payload


def load_config(path: str | Path) -> DaemonConfig:
    config = load_spec(path, DaemonConfig, "daemon config", resolve=True)
    _load_cards(config)
    check_handoffs(config)
    return config


def _load_cards(config: DaemonConfig) -> None:
    """Expand the tasks folder into tasks, if the config names one."""
    config.card_graphs = {}
    config.cards_by_task = {}
    if not config.cards:
        return
    folder = config.resolve_path(config.cards)
    if not folder.is_dir():
        raise SpecError(f"tasks folder does not exist: {folder}")
    # A typo in the project's memory fails here, where `poieo validate` and
    # the daemon's load can see it, never when a trigger fires at 3am.
    check_memory(config.base_dir)
    if config.learn is not None and not keeps_memory(config.base_dir):
        # Half an opt-in is how this feature dies quietly. A warning, not a
        # failure -- the file is still the opt-in.
        log.warning(
            "%s says `learn: %s`, but %s does not exist, so nothing will be learned. `poieo init` here starts one.",
            config.source_path,
            config.learn,
            config.layout().longterm(),
        )

    taken = {task.name for task in config.tasks}
    # Two passes: a card's generated prompt names the tasks it may tell, and
    # that is not known until the whole folder has been read.
    cards = load_cards(folder)
    roster = [card.slug for card in cards]
    for card in cards:
        task, graph = expand(card, roster=roster)
        if task.name in taken:
            raise SpecError(f"card '{card.source_path}' is already a task named '{task.name}'")
        taken.add(task.name)
        if not card.binding and not config.binding:
            raise SpecError(
                f"card '{card.slug}' names no binding and there is no default. "
                f"Add `binding: <file>` to the card, or to the project."
            )
        config.tasks.append(task)
        config.cards_by_task[task.name] = card
        if graph is not None:
            config.card_graphs[task.name] = graph


def config_for_tasks_folder(folder: Path) -> DaemonConfig:
    """The config `poieo daemon <folder>` stands for: run the cards in it.

    The argument says *which cards*, never where the project begins, so a
    ``poieo.yaml`` above still answers that: this becomes that project with its
    tasks folder swapped. Without a marker the folder is the project, and each
    card names its own binding because there is no file to hold a default.
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
    _load_cards(config)
    check_handoffs(config)
    return config


def _first_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """One cycle in the handoff wiring, as the names on it, or None.

    One is enough: listing every loop in a tangle is a wall of text.
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

    Not a validator on the config: a task card becomes a task only after the
    tasks folder has been read, and a handoff is entitled to name one.
    """
    known = {task.name: task for task in config.tasks}

    for task in config.tasks:
        for index, branch in enumerate(task.then):
            if branch.to is None:
                continue  # matched, and deliberately no further
            if branch.to == task.name:
                raise SpecError(
                    f"task '{task.name}' then[{index}] hands off to itself. A "
                    f"task's own next run is what `loop` and `carry_state` are for."
                )
            target = known.get(branch.to)
            if target is None:
                # Say what was there. A handoff naming a task that does not
                # exist is a typo far more often than it is a missing task.
                roster = ", ".join(sorted(n for n in known if n != task.name))
                raise SpecError(
                    f"task '{task.name}' then[{index}] hands off to unknown task "
                    f"'{branch.to}'. There is: {roster or '(nothing else)'}"
                )
            if not target.enabled:
                log.warning(
                    "task '%s' hands off to '%s', which is disabled: those "
                    "handoffs will be dropped. `enabled: false` is the off "
                    "switch, so this may well be deliberate.",
                    task.name,
                    branch.to,
                )
        if task.then and task.trigger.type == "loop":
            log.warning(
                "task '%s' hands off and runs on a `loop` trigger, so everything "
                "downstream inherits that pace. At most one handoff waits, and "
                "the rest are dropped.",
                task.name,
            )

    cycle = _first_cycle({f.name: [b.to for b in f.then if b.to is not None] for f in config.tasks})
    if cycle is not None:
        # A warning, not a failure: review -> fix -> review is a legitimate
        # feedback loop, and the chain-depth guard is what keeps it finite.
        log.warning(
            "handoffs form a cycle: %s. That is allowed -- the chain depth "
            "limit bounds it -- but check it is what you meant.",
            " -> ".join(cycle),
        )


def check_isolation(tasks: list[TaskSpec]) -> None:
    """Docker present, answering, and every named image already here.

    The slowest preflight in the codebase, and the only one that reaches
    outside the process: a task whose image was pruned last week must not
    discover it at 3am. Tasks that never asked are not probed at all, so a
    machine with no docker pays nothing.

    Which tasks reach here is the caller's business; load_tasks keeps disabled
    ones out.
    """
    wanted = [f for f in tasks if f.isolation]
    if not wanted:
        return

    from ..tools import docker  # late: nothing imports it unless asked

    ok, reason = docker.docker_available()
    if not ok:
        names = ", ".join(sorted(f.name for f in wanted))
        raise SpecError(f"task(s) {names} ask to run isolated, but {reason}")

    checked: set[str] = set()
    for task in wanted:
        image = task.isolation.image
        if image in checked:
            continue
        checked.add(image)
        if not docker.image_present(image):
            raise SpecError(
                f"task '{task.name}' runs isolated in '{image}', which is not on this machine. Run: docker pull {image}"
            )


def load_tasks(config: DaemonConfig, *, enabled_only: bool = True) -> list[LoadedTask]:
    """Parse every task's graph and binding, and verify roles resolve.

    Called at startup so a typo in any task surfaces immediately rather than at
    3am when its cron finally fires.
    """
    from ..providers import check_credentials
    from ..runtime.executor import preflight

    selected = [f for f in config.tasks if f.enabled or not enabled_only]
    # Only what will actually run: `poieo tasks` loads disabled tasks to list
    # them, and a disabled task whose image is gone must not block the listing.
    check_isolation([f for f in selected if f.enabled])

    graphs: dict[Path, GraphSpec] = {}
    bindings: dict[Path, BindingSpec] = {}
    loaded: list[LoadedTask] = []

    for task in selected:
        binding_path = config.binding_path(task).resolve()
        if binding_path not in bindings:
            bindings[binding_path] = load_binding(binding_path)

        workdir = config.workdir_path(task)
        if workdir is not None and not workdir.is_dir():
            raise SpecError(f"task '{task.name}': workdir does not exist: {workdir}")

        generated = config.card_graphs.get(task.name)
        if generated is None:
            graph_path = config.resolve_path(task.graph).resolve()
            if graph_path not in graphs:
                graphs[graph_path] = load_graph(graph_path)
            generated = graphs[graph_path]

        graph, binding = generated, bindings[binding_path]
        try:
            preflight(graph, binding, workdir=workdir)
            # Reads the environment, not a server, so it belongs at load time.
            # Enabled tasks only: a disabled one must still be listable.
            if task.enabled:
                check_credentials(binding, graph.roles())
        except Exception as exc:
            raise SpecError(f"task '{task.name}': {exc}") from exc

        # `role: classifer` still runs, on whatever `default` is -- a warning,
        # not a refusal, because falling back is what a default is for.
        # `default_role` is excluded (a node that named no role reaching the
        # default is the arrangement working), and a binding that declares no
        # roles is not asked at all: it is saying "one model for everything".
        strangers = binding.undeclared(graph.roles() - {graph.default_role}) if binding.roles else []
        if strangers:
            log.warning(
                "task '%s': graph '%s' asks for role(s) %s, which binding '%s' "
                "does not declare -- they will run on its default (%s). Check "
                "for a typo.",
                task.name,
                graph.name,
                ", ".join(strangers),
                binding.name,
                binding.default.model or "no model named",
            )

        loaded.append(
            LoadedTask(
                spec=task,
                graph=graph,
                binding=binding,
                binding_key=str(binding_path),
            )
        )
    return loaded
