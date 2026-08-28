"""The logical layer: what work happens, in what order.

A graph never names a model. Nodes name a *role* ("classifier", "writer"), and
:mod:`poieo.binding` maps roles onto physical endpoints.

Design: docs/graph.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ExpressionError, SpecError, describe_invalid
from .expr import compile_expr, validate_template


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
    type: Literal["agent", "command", "router"]
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
    timeout: float | None = Field(default=None, gt=0, le=600)
    # Laid over the process environment, never replacing it. Shells disagree
    # about `VAR=1 cmd`, and getting it wrong looks exactly like the command
    # running and failing.
    env: dict[str, str] = Field(default_factory=dict)

    # --- router nodes ---
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

    def _refuse_model_keys(self) -> None:
        named = [key for key in self._MODEL_KEYS if getattr(self, key)]
        if self.max_turns != type(self).model_fields["max_turns"].default:
            named.append("max_turns")
        if self.retry != RetrySpec():
            named.append("retry")
        if named:
            raise ValueError(
                f"{self.type} node '{self.id}' does not take "
                f"{'/'.join(named)}: it calls no model"
            )

    @model_validator(mode="after")
    def _check_shape(self) -> NodeSpec:
        if self.type != "command" and self.command is not None:
            raise ValueError(
                f"{self.type} node '{self.id}' does not take a command. Change "
                f"`type` to `command` for a step that runs one without a model"
            )
        if self.type == "command":
            if not self.command:
                raise ValueError(f"command node '{self.id}' requires a command")
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
                        f"agent node '{self.id}' names unknown toolset '{name}'; "
                        f"known: {sorted(TOOLSETS)}"
                    )
        if self.type == "router":
            if self.workdir or self.tools:
                raise ValueError(
                    f"router node '{self.id}' does not take workdir/tools"
                )
            if not self.branches:
                raise ValueError(f"router node '{self.id}' requires at least one branch")
            if self.prompt or self.role:
                raise ValueError(
                    f"router node '{self.id}' does not call a model; drop prompt/role"
                )
            if self.next:
                raise ValueError(
                    f"router node '{self.id}' routes via branches/default, not next"
                )
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
                    raise ValueError(
                        f"node '{node.id}' {label} points at unknown node '{target}'"
                    )

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
        return {
            n.role or self.default_role
            for n in self.nodes
            if n.type == "agent"
        }


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


def load_graph(path: str | Path) -> GraphSpec:
    """Load and fully validate a graph file."""
    path = Path(path)
    data = load_document(path)
    try:
        graph = GraphSpec.model_validate(data)
    except Exception as exc:
        # A node's settings are as much a part of a graph file as the graph's
        # own, so both sets are what a near-miss is measured against.
        raise SpecError(
            f"{path}: invalid graph: "
            f"{describe_invalid(exc, tuple(GraphSpec.model_fields) + tuple(NodeSpec.model_fields))}"
        ) from exc
    graph.source_path = path
    return graph
