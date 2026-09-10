"""Validate and publish browser-authored steps as an ordinary task and graph.

Design: docs/web.md
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..binding import BindingSpec
from ..errors import SpecError, describe_invalid
from ..graph import GraphSpec
from ..runtime.executor import preflight


def validate_steps(document: Any, binding: BindingSpec, folder: Path) -> GraphSpec:
    if not isinstance(document, dict):
        raise SpecError("steps must be a graph document, not a file path")
    try:
        graph = GraphSpec.model_validate(document)
    except ValidationError as exc:
        raise SpecError(describe_invalid(exc)) from exc
    # A node-specific folder can bypass both the browser's folder fence and
    # the task's private copy. Browser-authored steps share the chosen folder.
    if any(node.workdir is not None for node in graph.nodes):
        raise SpecError("steps made here use the task's folder; remove step-specific workdir settings")
    preflight(graph, binding, workdir=folder)
    return graph


def _publish(path: Path, text: str) -> None:
    scratch = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        scratch.write_text(text, encoding="utf-8")
        # The watcher must see complete documents. A link publishes without
        # replacing an existing file, including one created after validation.
        os.link(scratch, path)
    finally:
        scratch.unlink(missing_ok=True)


def publish_steps(path: Path, card_text: str, graph: GraphSpec) -> None:
    target = path.with_name(f"{path.stem}.graph.yaml")
    graph_text = yaml.safe_dump(
        graph.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True),
        allow_unicode=True,
        sort_keys=False,
    )
    _publish(target, graph_text)
    try:
        # Graphs alone are ignored by the task loader. Publishing the card
        # last is the moment the complete task becomes available to the scan.
        _publish(path, card_text)
    except OSError:
        target.unlink(missing_ok=True)
        raise
