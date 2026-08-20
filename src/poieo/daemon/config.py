"""Daemon configuration: which graphs run, on what trigger, against which binding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..binding import BindingSpec, load_binding
from ..errors import SpecError
from ..graph import GraphSpec, load_document, load_graph
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

    source_path: Path | None = Field(default=None, exclude=True)

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
        return payload


def load_config(path: str | Path) -> DaemonConfig:
    path = Path(path)
    data = load_document(path)
    try:
        config = DaemonConfig.model_validate(data)
    except Exception as exc:
        raise SpecError(f"{path}: invalid daemon config: {exc}") from exc
    config.source_path = path.resolve()
    return config


def load_flows(config: DaemonConfig, *, enabled_only: bool = True) -> list[LoadedFlow]:
    """Parse every flow's graph and binding, and verify roles resolve.

    Called at startup so a typo in any flow surfaces immediately rather than at
    3am when its cron finally fires.
    """
    from ..runtime.executor import preflight

    graphs: dict[Path, GraphSpec] = {}
    bindings: dict[Path, BindingSpec] = {}
    loaded: list[LoadedFlow] = []

    for flow in config.flows:
        if enabled_only and not flow.enabled:
            continue
        graph_path = config.resolve_path(flow.graph).resolve()
        binding_path = config.binding_path(flow).resolve()
        if graph_path not in graphs:
            graphs[graph_path] = load_graph(graph_path)
        if binding_path not in bindings:
            bindings[binding_path] = load_binding(binding_path)

        graph, binding = graphs[graph_path], bindings[binding_path]
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
