"""Node implementations. One class per ``NodeSpec.type``."""

from __future__ import annotations

import abc
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from ..errors import ExpressionError, NodeError, ProviderError, RunAborted
from ..expr import evaluate, render, unwrap
from ..graph import NodeSpec
from ..providers import LLMRequest, LLMResponse
from ..tools import DEFAULT_TOOLSETS, LocalExecutor
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


async def call_with_retry(spec: NodeSpec, provider, request: LLMRequest, ctx: RunContext) -> LLMResponse:
    """Call the provider with exponential backoff retry logic."""
    retry = spec.retry
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
                node_id=spec.id,
                attempt=attempt,
                delay=delay,
                error=str(exc),
            )
            await asyncio.sleep(delay)
    raise NodeError(
        f"node '{spec.id}' failed after {retry.attempts} attempt(s): {last}",
        node_id=spec.id,
    ) from last


def shape_output(spec: NodeSpec, text: str) -> Any:
    """Shape the model output according to the node's output configuration."""
    out = spec.output
    if out.format == "text":
        return text.strip()
    data = _parse_json(text, spec.id)
    if out.path:
        cursor: Any = data
        for part in out.path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                raise NodeError(
                    f"node '{spec.id}': output path '{out.path}' "
                    f"is missing from the parsed JSON",
                    node_id=spec.id,
                )
            cursor = cursor[part]
        return cursor
    return data


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

        response = await call_with_retry(self.spec, provider, request, ctx)

        ctx.usage = ctx.usage.merge(response.usage)
        output = shape_output(self.spec, response.text)
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



def _clip(value: Any, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


class AgentNode(Node):
    """Hands the model tools and loops until it answers without one.

    "Keeps working" belongs to the graph and the daemon; this loop is only
    the mechanics of one step doing its job, bounded by max_turns.
    """

    async def run(self, ctx: RunContext) -> NodeResult:
        spec = self.spec
        role = spec.role or ctx.graph.default_role
        resolved = ctx.binding.resolve(role, spec.params or None)
        provider = ctx.pool.get(resolved.provider_name)

        scope = ctx.scope()
        try:
            prompt = render(spec.prompt or "", scope)
            system = render(spec.system, scope) if spec.system else None
            workdir = Path(render(spec.workdir or "", scope)).expanduser()
        except ExpressionError as exc:
            raise NodeError(f"node '{spec.id}': {exc}", node_id=spec.id) from exc
        if not workdir.is_dir():
            raise NodeError(
                f"node '{spec.id}': workdir does not exist: {workdir}", node_id=spec.id
            )

        executor = LocalExecutor(workdir, spec.tools or DEFAULT_TOOLSETS)
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        turns = 0
        tool_call_count = 0

        while True:
            if ctx.cancel is not None and ctx.cancel.is_set():
                raise RunAborted(f"cancelled during agent node '{spec.id}'")
            turns += 1
            request = LLMRequest(
                model=resolved.model,
                messages=list(messages),
                system=system,
                params=dict(resolved.params),
                role=role,
                tools=executor.definitions(),
            )
            response = await call_with_retry(spec, provider, request, ctx)
            ctx.usage = ctx.usage.merge(response.usage)

            if not response.tool_calls:
                break
            if turns >= spec.max_turns:
                raise NodeError(
                    f"node '{spec.id}' hit max_turns ({spec.max_turns}) "
                    f"with tool calls still pending",
                    node_id=spec.id,
                )

            assistant_turn: dict[str, Any] = {
                "role": "assistant",
                "content": response.text,
                "tool_calls": [
                    {"id": c.id, "name": c.name, "arguments": c.arguments}
                    for c in response.tool_calls
                ],
            }
            raw = response.meta.get("raw_content")
            if raw:
                # Provider-specific blocks (e.g. anthropic thinking) replayed
                # verbatim on the next turn; other providers ignore the key.
                assistant_turn["raw_content"] = raw
            messages.append(assistant_turn)
            for call in response.tool_calls:
                started = time.monotonic()
                result = await executor.execute(call)
                tool_call_count += 1
                ctx.emit(
                    "node_tool_call",
                    node_id=spec.id,
                    turn=turns,
                    name=call.name,
                    arguments=_clip(call.arguments),
                    result=_clip(result.text),
                    error=result.error,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result.text}
                )

        output = shape_output(spec, response.text)
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
                "turns": turns,
                "tool_calls": tool_call_count,
            },
        )


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
    "agent": AgentNode,
}


def build_node(spec: NodeSpec) -> Node:
    cls = NODE_TYPES.get(spec.type)
    if cls is None:  # pragma: no cover - the schema rejects unknown types first
        raise NodeError(f"unknown node type '{spec.type}'", node_id=spec.id)
    return cls(spec)
