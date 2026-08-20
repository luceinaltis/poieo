"""Node implementations. One class per ``NodeSpec.type``."""

from __future__ import annotations

import abc
import asyncio
import json
import re
from typing import Any

from ..errors import ExpressionError, NodeError, ProviderError
from ..expr import evaluate, render, unwrap
from ..graph import NodeSpec
from ..providers import LLMRequest
from .context import NodeResult, RunContext

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class Node(abc.ABC):
    """Base class; register subclasses in :data:`NODE_TYPES`."""

    def __init__(self, spec: NodeSpec):
        self.spec = spec

    @abc.abstractmethod
    async def run(self, ctx: RunContext) -> NodeResult:
        ...


def _parse_json(text: str, node_id: str) -> Any:
    """Parse a model's JSON output, tolerating a markdown fence around it."""
    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        # A model that adds a sentence before the object is common enough to
        # be worth one salvage attempt before failing the node.
        start = min((i for i in (candidate.find("{"), candidate.find("[")) if i >= 0), default=-1)
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise NodeError(
            f"node '{node_id}' expected JSON output but got: {text[:200]!r}",
            node_id=node_id,
        ) from exc


class LLMNode(Node):
    """Renders a prompt, calls the model bound to this node's role, stores the result."""

    async def run(self, ctx: RunContext) -> NodeResult:
        spec = self.spec
        role = spec.role or ctx.graph.default_role
        resolved = ctx.binding.resolve(role, spec.params or None)
        provider = ctx.pool.get(resolved.provider_name)

        scope = ctx.scope()
        try:
            prompt = render(spec.prompt or "", scope)
            system = render(spec.system, scope) if spec.system else None
        except ExpressionError as exc:
            raise NodeError(f"node '{spec.id}': {exc}", node_id=spec.id) from exc

        request = LLMRequest(
            model=resolved.model,
            messages=[{"role": "user", "content": prompt}],
            system=system,
            params=dict(resolved.params),
            role=role,
        )

        response = await self._call_with_retry(provider, request, ctx)

        ctx.usage = ctx.usage.merge(response.usage)
        output = self._shape_output(response.text)
        ctx.record_output(spec.id, output, spec.output.as_)
        if spec.output.into_state:
            ctx.state[spec.output.into_state] = unwrap(output)

        return NodeResult(
            node_id=spec.id,
            next_node=spec.next,
            output=output,
            meta={
                "role": role,
                "binding": resolved.describe(),
                "model": response.model,
                "usage": response.usage.as_dict(),
                "stop_reason": response.stop_reason,
            },
        )

    async def _call_with_retry(self, provider, request: LLMRequest, ctx: RunContext):
        retry = self.spec.retry
        last: ProviderError | None = None
        for attempt in range(1, retry.attempts + 1):
            try:
                return await provider.complete(request)
            except ProviderError as exc:
                last = exc
                if not exc.retryable or attempt == retry.attempts:
                    break
                delay = retry.backoff * (2 ** (attempt - 1))
                ctx.emit(
                    "node_retry",
                    node_id=self.spec.id,
                    attempt=attempt,
                    delay=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
        raise NodeError(
            f"node '{self.spec.id}' failed after {retry.attempts} attempt(s): {last}",
            node_id=self.spec.id,
        ) from last

    def _shape_output(self, text: str) -> Any:
        out = self.spec.output
        if out.format == "text":
            return text.strip()
        data = _parse_json(text, self.spec.id)
        if out.path:
            cursor: Any = data
            for part in out.path.split("."):
                if not isinstance(cursor, dict) or part not in cursor:
                    raise NodeError(
                        f"node '{self.spec.id}': output path '{out.path}' "
                        f"is missing from the parsed JSON",
                        node_id=self.spec.id,
                    )
                cursor = cursor[part]
            return cursor
        return data


class RouterNode(Node):
    """Picks the next node by evaluating branch conditions in order."""

    async def run(self, ctx: RunContext) -> NodeResult:
        spec = self.spec
        scope = ctx.scope()
        for index, branch in enumerate(spec.branches):
            try:
                matched = bool(evaluate(branch.when, scope))
            except ExpressionError as exc:
                raise NodeError(
                    f"node '{spec.id}' branch[{index}] ({branch.when!r}): {exc}",
                    node_id=spec.id,
                ) from exc
            if matched:
                label = branch.label or branch.when
                ctx.record_output(spec.id, label, spec.output.as_)
                return NodeResult(
                    node_id=spec.id,
                    next_node=branch.to,
                    output=label,
                    meta={"matched": index, "condition": branch.when, "label": label},
                )

        ctx.record_output(spec.id, "default", spec.output.as_)
        return NodeResult(
            node_id=spec.id,
            next_node=spec.default,
            output="default",
            meta={"matched": None, "label": "default"},
        )


NODE_TYPES: dict[str, type[Node]] = {
    "llm": LLMNode,
    "router": RouterNode,
}


def build_node(spec: NodeSpec) -> Node:
    cls = NODE_TYPES.get(spec.type)
    if cls is None:  # pragma: no cover - the schema rejects unknown types first
        raise NodeError(f"unknown node type '{spec.type}'", node_id=spec.id)
    return cls(spec)
