"""The logical layer: what work happens, in what order.

A graph never names a model. Nodes name a *role* ("classifier", "writer"), and
:mod:`poieo.binding` maps roles onto physical endpoints.

Design: docs/graph.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ExpressionError, SpecError, describe_invalid
from .expr import compile_expr, reaches_for_run_data, validate_template


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutputSpec(_Spec):
    """Where a node's result lands in the run scope."""

    # Alias exposed at the top level of the scope, e.g. `{{ category }}`.
    as_: str | None = Field(default=None, alias="as")
    # "text" keeps the raw completion; "json" parses it into data first.
    format: Literal["text", "json"] = "text"
    # For json output, store only this key of the parsed object.
    path: str | None = None
    # Also merge the result into the persistent `state` under this key.
    into_state: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class UiSpec(_Spec):
    """Canvas coordinates. Written by the editor, ignored by the runtime."""

    x: float = 0
    y: float = 0


class RetrySpec(_Spec):
    attempts: int = Field(default=1, ge=1, le=10)
    backoff: float = Field(default=1.0, ge=0.0, le=60.0)


class Branch(_Spec):
    """One arm of a router: a condition and the node to jump to."""

    when: str
    to: str | None = None
    label: str | None = None

    @field_validator("when")
    @classmethod
    def _parse_condition(cls, value: str) -> str:
        compile_expr(value)
        return value


class NodeSpec(_Spec):
    id: str
    type: Literal["agent", "command", "router", "confirm"]
    description: str | None = None

    # --- model nodes ---
    role: str | None = None
    system: str | None = None
    prompt: str | None = None
    output: OutputSpec = Field(default_factory=OutputSpec)
    retry: RetrySpec = Field(default_factory=RetrySpec)
    # Per-node overrides layered on top of whatever the binding resolves to.
    params: dict[str, Any] = Field(default_factory=dict)

    # --- command nodes ---
    # The command runs where the model's would: through the executor seam, so
    # a task that asked to be fenced is fenced here too.
    command: str | None = None
    # Code the node carries, handed to `language`'s interpreter on stdin. The
    # alternative is a shell string, where a quote or a colon or a newline all
    # mean something on the way past.
    script: str | None = None
    language: str | None = None
    timeout: float | None = Field(default=None, gt=0, le=600)
    # Laid over the process environment, never replacing it. Shells disagree
    # about `VAR=1 cmd`, and getting it wrong looks exactly like the command
    # running and failing.
    env: dict[str, str] = Field(default_factory=dict)

    # --- router nodes ---
    # --- confirm nodes ---
    # What a person may answer. A fixed set, never free text: an answer read
    # out of prose is the `'HOLD' in text` guess this node exists to replace.
    choices: list[str] = Field(default_factory=list)

    branches: list[Branch] = Field(default_factory=list)
    default: str | None = None

    # --- agent nodes ---
    # Every tool call is confined to this directory. Templates allowed.
    workdir: str | None = None
    # Toolset names from poieo.tools.TOOLSETS. Absent means **no tools**: a
    # node that can touch the project says so, and a graph's diff shows at a
    # glance which of its steps can. Principle 2 keeps the folder explicit for
    # the same reason, and hands are that rule one level up.
    tools: list[str] | None = None
    # Upper bound on model calls in one node execution.
    max_turns: int = Field(default=20, ge=1, le=200)
    # How long this node may work, as a duration. `None` means only `max_turns`
    # bounds it, which is how this began and is the wrong unit for the job:
    # measured in one run, a turn cost between 15 and 1,629 output tokens and
    # took between five seconds and seven minutes. "Forty turns" is not a
    # budget anybody can reason about. "This fires hourly, so a step must not
    # take an hour" is -- and the harm an unbounded step does is precisely that
    # it outlives its own schedule and blocks what was queued behind it.
    deadline: float | None = Field(default=None, gt=0)

    # `None` means "this node ends the run".
    next: str | None = None

    # Editor-only: where this node sits on the canvas.
    ui: UiSpec | None = None

    @field_validator("type", mode="before")
    @classmethod
    def _was_renamed(cls, value: Any) -> Any:
        """`llm` was a node until there was one model node. Say so.

        `Literal` would answer "Input should be 'agent' or 'router'", which is
        true and no help to someone holding a graph that worked last week.
        """
        if value == "llm":
            raise ValueError(
                "node type 'llm' is now 'agent' with no tools. Rename it, and "
                "add `tools: [files, shell]` only if the node should have hands"
            )
        return value

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not value or not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"node id {value!r} must be alphanumeric (- and _ allowed)")
        if value[0].isdigit():
            raise ValueError(f"node id {value!r} must not start with a digit")
        return value

    # Keys that only mean something when a model is being called. A node that
    # calls none must refuse them: a key that does nothing is worse than one
    # that is missing, because it reads as configured.
    _MODEL_KEYS = ("role", "system", "prompt", "params", "tools")

    def _refuse_model_keys(self, keep: str = "") -> None:
        """``keep`` names the one key this type does use for something else --
        a confirm node's ``prompt`` is read by a person, not sent anywhere."""
        named = [key for key in self._MODEL_KEYS if key != keep and getattr(self, key)]
        if self.max_turns != type(self).model_fields["max_turns"].default:
            named.append("max_turns")
        if self.retry != RetrySpec():
            named.append("retry")
        if named:
            raise ValueError(f"{self.type} node '{self.id}' does not take {'/'.join(named)}: it calls no model")

    @model_validator(mode="after")
    def _check_shape(self) -> NodeSpec:
        if self.type != "command" and self.command is not None:
            raise ValueError(
                f"{self.type} node '{self.id}' does not take a command. Change "
                f"`type` to `command` for a step that runs one without a model"
            )
        if self.type == "command":
            for name, value in self.env.items():
                # `env` is rendered like a command and a prompt, so it is
                # checked where they are -- and it is the one way a compiled
                # script gets anything from the run.
                try:
                    validate_template(value)
                except ExpressionError as exc:
                    raise ValueError(f"node '{self.id}', env '{name}': {exc}") from exc
            if self.command and self.script:
                raise ValueError(
                    f"command node '{self.id}' takes a command or a script, not "
                    f"both: one is a line for a shell, the other is code for an "
                    f"interpreter"
                )
            if self.script and not self.language:
                raise ValueError(
                    f"command node '{self.id}' has a script but no language. "
                    f"Nothing can be read off the code itself, and guessing "
                    f"wrong runs the wrong interpreter over it"
                )
            if self.language and not self.script:
                raise ValueError(f"command node '{self.id}' names a language but has no script")
            if self.language:
                # late import; tools pulls in providers
                from .tools import COMPILED, LANGUAGES, is_compiled, known_language

                if not known_language(self.language):
                    raise ValueError(
                        f"command node '{self.id}' names unknown language "
                        f"'{self.language}'; known: "
                        f"{sorted(set(LANGUAGES) | set(COMPILED))}"
                    )
                if is_compiled(self.language):
                    # A compiled script is not a template: it is cached by its
                    # own text, and a template would render differently each
                    # run, so the cache would never hit and would grow without
                    # bound. So `{{` here means what the *language* means by
                    # it -- `[][]int{{1,2},{3,4}}` is ordinary Go, and passes.
                    #
                    # What is worth catching at load is the mistake the rule
                    # invites: reaching for run data that will never arrive.
                    reach = reaches_for_run_data(self.script or "")
                    if reach is not None:
                        raise ValueError(
                            f"command node '{self.id}': a {self.language} script is "
                            f"compiled and cached by its own text, so {reach} is not "
                            f"substituted. Put what varies in `env:` and read it at "
                            f"run time"
                        )
                else:
                    try:
                        validate_template(self.script or "")
                    except ExpressionError as exc:
                        raise ValueError(f"node '{self.id}': {exc}") from exc
            if not self.command and not self.script:
                raise ValueError(f"command node '{self.id}' requires a command or a script")
            # `command: |` is the readable way to write a long one, and it
            # adds a trailing newline. That is a spelling, not a second line.
            if self.command:
                # `command: |` is the readable way to write a long one, and it
                # adds a trailing newline. That is a spelling, not a second line.
                self.command = self.command.strip()
                if "\n" in self.command:
                    raise ValueError(
                        f"command node '{self.id}': a command is one command, and "
                        f"a second line is silently dropped by some shells -- the "
                        f"step reports success having run half of it. Chain with "
                        f"`&&`, give each line its own node, or use `script:`"
                    )
                # Rendered at run time, so checked at parse time -- the same
                # rule a prompt gets. A typo here used to wait for the trigger.
                try:
                    validate_template(self.command)
                except ExpressionError as exc:
                    raise ValueError(f"node '{self.id}': {exc}") from exc
            if self.branches:
                raise ValueError(f"command node '{self.id}' cannot declare branches")
            self._refuse_model_keys()
            # Same rule as an agent's: physical, so the task may supply it, and
            # a template so one graph can serve more than one folder.
            if self.workdir:
                try:
                    validate_template(self.workdir)
                except ExpressionError as exc:
                    raise ValueError(f"node '{self.id}': {exc}") from exc
        if self.type == "agent":
            if not self.prompt:
                raise ValueError(f"{self.type} node '{self.id}' requires a prompt")
            if self.branches:
                raise ValueError(f"{self.type} node '{self.id}' cannot declare branches")
            try:
                validate_template(self.prompt)
                if self.system:
                    validate_template(self.system)
            except ExpressionError as exc:
                raise ValueError(f"node '{self.id}': {exc}") from exc
            # A workdir is physical, and this is the logical layer: the task may
            # supply it instead. preflight() is where "nowhere to work" fails.
            if self.workdir:
                try:
                    validate_template(self.workdir)
                except ExpressionError as exc:
                    raise ValueError(f"node '{self.id}': {exc}") from exc
            from .tools import TOOLSETS  # late import; tools pulls in providers

            for name in self.tools or []:
                if name not in TOOLSETS:
                    raise ValueError(
                        f"agent node '{self.id}' names unknown toolset '{name}'; known: {sorted(TOOLSETS)}"
                    )
        if self.type == "router":
            if self.workdir or self.tools:
                raise ValueError(f"router node '{self.id}' does not take workdir/tools")
            if not self.branches:
                raise ValueError(f"router node '{self.id}' requires at least one branch")
            if self.prompt or self.role:
                raise ValueError(f"router node '{self.id}' does not call a model; drop prompt/role")
            if self.next:
                raise ValueError(f"router node '{self.id}' routes via branches/default, not next")
        if self.type != "confirm" and self.choices:
            raise ValueError(
                f"{self.type} node '{self.id}' does not offer choices. Change "
                f"`type` to `confirm` for a step that asks a person"
            )
        if self.type == "confirm":
            # It calls no model and runs nothing: it puts a question to the
            # person and the run ends there.
            self._refuse_model_keys(keep="prompt")
            if self.workdir:
                raise ValueError(f"confirm node '{self.id}' does not take a workdir: nothing runs there")
            if not self.prompt:
                raise ValueError(f"confirm node '{self.id}' has nothing to ask; give it a prompt")
            if self.branches or self.default:
                raise ValueError(
                    f"confirm node '{self.id}' does not branch: a person answers "
                    f"it, and the card's `then:` reads that answer"
                )
            if self.next:
                raise ValueError(
                    f"confirm node '{self.id}' ends the run -- the answer arrives "
                    f"after it, so what happens next is the card's `then:`"
                )
            if len(self.choices) < 2:
                raise ValueError(
                    f"confirm node '{self.id}' needs two choices or more: one is not a decision, and none is free text"
                )
            if len(set(self.choices)) != len(self.choices):
                raise ValueError(f"confirm node '{self.id}' offers the same choice twice")
            try:
                validate_template(self.prompt)
            except ExpressionError as exc:
                raise ValueError(f"node '{self.id}': {exc}") from exc
        return self


class GraphSpec(_Spec):
    """A whole workflow: nodes, wiring, and the loop guard."""

    name: str
    version: int = 1
    description: str | None = None
    entry: str
    nodes: list[NodeSpec]
    # Seed for the persistent `state` mapping on the first iteration.
    state: dict[str, Any] = Field(default_factory=dict)
    # Guards cycles. A graph may legitimately loop; this bounds how long.
    max_steps: int = Field(default=100, ge=1, le=10_000)
    # Default role for model nodes that do not name one.
    default_role: str = "default"

    # Populated after validation; not part of the authored document.
    source_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _check_wiring(self) -> GraphSpec:
        ids = [n.id for n in self.nodes]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate node ids: {sorted(duplicates)}")
        known = set(ids)
        if self.entry not in known:
            raise ValueError(f"entry node '{self.entry}' is not defined")

        for node in self.nodes:
            targets = [("next", node.next), ("default", node.default)]
            targets += [(f"branch[{i}].to", b.to) for i, b in enumerate(node.branches)]
            for label, target in targets:
                if target is not None and target not in known:
                    raise ValueError(f"node '{node.id}' {label} points at unknown node '{target}'")

        unreachable = known - self._reachable()
        if unreachable:
            raise ValueError(f"unreachable nodes: {sorted(unreachable)}")
        return self

    def _reachable(self) -> set[str]:
        by_id = {n.id: n for n in self.nodes}
        seen: set[str] = set()
        stack = [self.entry]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            node = by_id[current]
            for target in [node.next, node.default, *(b.to for b in node.branches)]:
                if target is not None:
                    stack.append(target)
        return seen

    def node(self, node_id: str) -> NodeSpec:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise SpecError(f"graph '{self.name}' has no node '{node_id}'")

    def roles(self) -> set[str]:
        """Every logical role this graph needs a binding for."""
        return {n.role or self.default_role for n in self.nodes if n.type == "agent"}


def load_document(path: str | Path) -> dict[str, Any]:
    """Read a YAML or JSON document from disk."""
    path = Path(path)
    if not path.exists():
        raise SpecError(f"file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix in {".json"}:
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise SpecError(f"{path}: could not parse: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"{path}: expected a mapping at the top level")
    return data


_Spec_co = TypeVar("_Spec_co", bound=BaseModel)


def load_spec(
    path: str | Path,
    model: type[_Spec_co],
    noun: str,
    *,
    also: tuple[type[BaseModel], ...] = (),
    resolve: bool = False,
) -> _Spec_co:
    """Read one configuration file, or say what is wrong with it in the
    user's words.

    Five loaders -- a binding, a graph, a card, a project and a daemon config
    -- had this same body: read the document, validate it, and turn a refusal
    into `SpecError` with `describe_invalid`'s nearest-real-key suggestion.
    That last part is the point. `_Spec` sets `extra="forbid"` so a key poieo
    does not recognise is a loud failure, and this is where the failure becomes
    a sentence rather than a pydantic dump (`docs/conventions.md`).

    ``also`` names the *nested* models whose fields also belong to this file.
    A graph file carries node settings as much as its own, so a typo inside a
    node should be measured against both -- and only the graph loader did that,
    which is why four of the five gave no "did you mean" for a typo one level
    down.

    ``resolve`` is a divergence rather than a decision: the project and daemon
    loaders resolve `source_path`, the other three do not, and callers that
    need an absolute one bolt `.resolve()` on themselves. Named here so it is
    one flag to look at rather than five files to compare.
    """
    path = Path(path)
    data = load_document(path)
    known = tuple(model.model_fields) + tuple(name for nested in also for name in nested.model_fields)
    try:
        spec = model.model_validate(data)
    except Exception as exc:
        raise SpecError(f"{path}: invalid {noun}: {describe_invalid(exc, known)}") from exc
    spec.source_path = path.resolve() if resolve else path  # type: ignore[attr-defined]
    return spec


def load_graph(path: str | Path) -> GraphSpec:
    """Load and fully validate a graph file."""
    return load_spec(path, GraphSpec, "graph", also=(NodeSpec,))
