"""Node implementations. One class per ``NodeSpec.type``."""

from __future__ import annotations

import abc
import asyncio
import json
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..binding import ResolvedModel
from ..errors import ExpressionError, NodeError, ProviderError, RunAborted
from ..expr import evaluate, render, unwrap
from ..graph import NodeSpec
from ..providers import LLMRequest, LLMResponse
from ..tools import LANGUAGES, ToolError, make_executor
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


def _rendered(spec: NodeSpec, template: str, scope: dict[str, Any]) -> str:
    """Render one of a node's templates, failing in the node's own voice, so a
    typo in a prompt, a system block or a workdir all read alike in a run log."""
    try:
        return render(template, scope)
    except ExpressionError as exc:
        raise NodeError(f"node '{spec.id}': {exc}", node_id=spec.id) from exc


@dataclass(slots=True)
class _Bound:
    """What a node that talks to a model works out before its first request:
    the logical half (role, templates) having met the physical half."""

    role: str
    resolved: ResolvedModel
    provider: Any
    prompt: str
    system: str | None
    scope: dict[str, Any]

    def request(self, messages: list[dict[str, Any]], **extra: Any) -> LLMRequest:
        return LLMRequest(
            model=self.resolved.model,
            messages=messages,
            system=self.system,
            params=dict(self.resolved.params),
            role=self.role,
            **extra,
        )


def _prepare(spec: NodeSpec, ctx: RunContext) -> _Bound:
    """Pick the role, resolve it, take the provider, render the templates.

    Both model-calling node types open identically.
    """
    role = spec.role or ctx.graph.default_role
    resolved = ctx.binding.resolve(role, spec.params or None)
    scope = ctx.scope()
    return _Bound(
        role=role,
        resolved=resolved,
        provider=ctx.pool.get(resolved.provider_name),
        prompt=_rendered(spec, spec.prompt or "", scope),
        system=_rendered(spec, spec.system, scope) if spec.system else None,
        scope=scope,
    )


def _finish(
    spec: NodeSpec,
    ctx: RunContext,
    bound: _Bound,
    response: LLMResponse,
    **extra: Any,
) -> NodeResult:
    """Shape what the model said, record it, and describe the step.

    The same for every node that calls a model, but for what it adds to
    ``meta``: one with tools counts its turns and its tool calls, one
    without has neither to count.
    """
    output = shape_output(spec, response.text)
    ctx.record_output(spec.id, output, spec.output.as_)
    if spec.output.into_state:
        ctx.state[spec.output.into_state] = unwrap(output)

    return NodeResult(
        node_id=spec.id,
        next_node=spec.next,
        output=output,
        meta={
            "role": bound.role,
            "binding": bound.resolved.describe(),
            "model": response.model,
            "usage": response.usage.as_dict(),
            "stop_reason": response.stop_reason,
            **extra,
        },
    )


# What an endpoint calls "I stopped because I ran out of room", by dialect.
_CUT_OFF = {"length", "max_tokens"}


def _clip(value: Any, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


# How large a conversation may get before its older observations are dropped,
# in characters -- the unit the tools already measure their own output in
# (`_READ_CAP`, `_OUTPUT_CAP`), and one that needs no tokenizer to read.
_CONTEXT_CAP = 120_000
# How many of the most recent tool results survive a clearing, whole.
_KEEP_RESULTS = 3
_CLEARED = "[cleared to save room -- call the tool again if you still need this]"


def _conversation_size(messages: list[dict[str, Any]]) -> int:
    """Roughly how much there is to send, in characters.

    Tool call arguments count: a `write_file` carries a whole file body in
    them, and a measure that skipped it would call the largest thing in the
    conversation weightless.
    """
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        calls = message.get("tool_calls")
        if calls:
            total += len(json.dumps(calls, ensure_ascii=False, default=str))
    return total


def _clear_old_results(messages: list[dict[str, Any]]) -> int:
    """Replace all but the most recent tool results with a note, in place.

    The conversation is the whole of what an agent node resends every turn,
    and tool results are nearly all of it -- one file read is tens of
    thousands of characters, and it is sent again on every turn after it for
    as long as the node runs. Nothing here ever removed anything, so the cost
    of a step grew with the square of its length and a model that had read
    twenty files was reasoning inside a haystack of its own making.

    **What goes is the result, never the request.** The assistant turn that
    asked for the file stays exactly as it was, so the model still knows it
    has read this file; and the tools are offered again on every turn, so it
    can read it again if the contents turn out to matter. That is what makes
    this lossless in a way summarizing the same history would not be: the
    worst case is one repeated call, not a fact gone for good.

    Returns the characters freed, which is zero when there was nothing old
    enough to clear -- the caller says nothing in that case rather than
    reporting work it did not do.
    """
    results = [i for i, message in enumerate(messages) if message.get("role") == "tool"]
    freed = 0
    for index in results[:-_KEEP_RESULTS] if _KEEP_RESULTS else results:
        content = messages[index].get("content")
        if not isinstance(content, str) or content == _CLEARED:
            continue
        freed += len(content) - len(_CLEARED)
        messages[index] = {**messages[index], "content": _CLEARED}
    return freed


# The second cap, and the last resort. Clearing empties tool results but the
# turns themselves keep piling up -- a model's own reasoning, and tool call
# arguments, which for a `write_file` are a whole file. Past this the older
# turns are folded into one summary. Well above `_CONTEXT_CAP` on purpose:
# clearing is free and reversible, and this is neither.
_COMPACT_CAP = 220_000
# How many of the most recent turns are left as they were.
_KEEP_TURNS = 4
# The least a fold may reclaim to be worth the model call that writes it.
#
# Without a floor this fires every turn once it has fired once: a fold leaves
# exactly `_KEEP_TURNS` turns behind it, so the next turn is one over again and
# folding a single turn away costs a whole model call. Anthropic's clearing has
# a `clear_at_least` for the same reason.
_FOLD_AT_LEAST = 20_000
_SUMMARY_HEADER = "What has happened so far, in your own earlier words:"
_SUMMARY_PROMPT = """\
Below is the earlier part of your own working session, which is about to be
replaced by what you write here. Write down what the rest of the session
cannot do without: the task as you now understand it, what you have tried and
what came of it, what you have decided and why, which files matter, and what
is still broken or unfinished. Be specific -- name files, functions and error
messages. Write nothing else: no preamble, no offer to help.

"""


def _transcript(messages: list[dict[str, Any]]) -> str:
    """The part being folded away, as something a model can read back."""
    lines: list[str] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role == "assistant":
            calls = ", ".join(
                f"{c['name']}({json.dumps(c.get('arguments'), ensure_ascii=False, default=str)})"
                for c in (message.get("tool_calls") or [])
            )
            lines.append(f"you: {content}" if content else "you:")
            if calls:
                lines.append(f"you called: {calls}")
        elif role == "tool":
            lines.append(f"the tool answered: {content}")
        else:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _fold_point(messages: list[dict[str, Any]]) -> int | None:
    """Where the history may be cut without orphaning a tool result.

    A result answers a call, and a provider rejects one whose call is gone --
    so the cut has to land on a turn boundary, which is where the model
    speaks. Returns None when there is not enough behind the kept turns to be
    worth folding.
    """
    spoke = [i for i, message in enumerate(messages) if message.get("role") == "assistant"]
    if len(spoke) <= _KEEP_TURNS:
        return None
    cut = spoke[-_KEEP_TURNS]
    # Everything before the cut but after the task itself; less than that and
    # a model call would buy nothing.
    return cut if cut > 1 else None


async def _compact(
    spec: NodeSpec,
    ctx: RunContext,
    bound: _Bound,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fold the older turns into a summary, and carry on from it.

    The summary is written into the first message rather than added beside it.
    That message is the task, the task is never folded away, and keeping the
    two together avoids asking either API to accept two user turns in a row.

    A summary that cannot be written is not worth losing the step over: the
    history is left whole, `node_compact_failed` says so, and the run carries
    on to fail honestly on room if it is going to.
    """
    cut = _fold_point(messages)
    if cut is None:
        return messages
    older, tail = messages[1:cut], messages[cut:]
    if _conversation_size(older) < _FOLD_AT_LEAST:
        return messages
    before = _conversation_size(messages)

    request = bound.request([{"role": "user", "content": _SUMMARY_PROMPT + _transcript(older)}])
    try:
        response = await call_with_retry(spec, bound.provider, request, ctx)
    except NodeError as exc:
        # `call_with_retry` has already spent this node's retry budget and
        # wrapped whatever went wrong, so this is the end of the attempt rather
        # than the start of one. It ends here and not up the stack: the step
        # itself is still fine.
        ctx.emit("node_compact_failed", node_id=spec.id, error=str(exc))
        return messages
    ctx.usage = ctx.usage.merge(response.usage)

    task = messages[0]
    folded = [
        {**task, "content": f"{task.get('content') or ''}\n\n{_SUMMARY_HEADER}\n{response.text}"},
        *tail,
    ]
    ctx.emit(
        "node_compacted",
        node_id=spec.id,
        folded=before - _conversation_size(folded),
        kept=_KEEP_TURNS,
    )
    return folded


class AgentNode(Node):
    """Renders a prompt, calls the model, and loops while it asks for tools.

    Tools are the whole of what varies here. A node that names none is shown
    none, so it cannot ask for one, so the loop below runs once and breaks --
    which is what `type: agent` used to be, without a second node type to say
    it. Everything else follows from tools: the directory they work in, the
    executor that runs them, the turn budget the loop spends.

    "Keeps working" belongs to the graph and the daemon; this loop is only
    the mechanics of one step doing its job, bounded by max_turns.
    """

    async def run(self, ctx: RunContext) -> NodeResult:
        spec = self.spec
        bound = _prepare(spec, ctx)
        toolsets = spec.tools or []

        workdir = (
            Path(_rendered(spec, spec.workdir, bound.scope)).expanduser()
            if spec.workdir
            else ctx.workdir
        )
        if toolsets:
            if workdir is None:  # preflight should have caught this
                raise NodeError(f"node '{spec.id}': no workdir", node_id=spec.id)
            if not workdir.is_dir():
                raise NodeError(
                    f"node '{spec.id}': workdir does not exist: {workdir}",
                    node_id=spec.id,
                )

        # Nothing is built for a node with no tools: an executor can mean a
        # container, and standing one up to offer nothing would be a cost with
        # no purchase.
        async with AsyncExitStack() as stack:
            executor = (
                await stack.enter_async_context(
                    make_executor(workdir, toolsets, ctx.tool_context)  # type: ignore[arg-type]
                )
                if toolsets
                else None
            )
            offered = executor.definitions() if executor is not None else []
            messages: list[dict[str, Any]] = [{"role": "user", "content": bound.prompt}]
            turns = 0
            tool_call_count = 0

            while True:
                if ctx.cancel is not None and ctx.cancel.is_set():
                    raise RunAborted(f"cancelled during agent node '{spec.id}'")
                turns += 1
                # Only past the cap, and then all at once. Clearing on every
                # turn would move the boundary forward by one result each
                # time, and an endpoint that caches prompt prefixes would find
                # a different prefix every turn -- paying the whole
                # conversation again to save part of it.
                if _conversation_size(messages) > _CONTEXT_CAP:
                    freed = _clear_old_results(messages)
                    if freed:
                        ctx.emit(
                            "node_context_cleared",
                            node_id=spec.id,
                            turn=turns,
                            freed=freed,
                            kept=_KEEP_RESULTS,
                        )
                # And if emptying the results was not enough -- the turns
                # themselves accumulate, and a `write_file` carries a whole
                # file in its arguments -- the older ones are folded into a
                # summary. Second because it costs a model call and cannot be
                # undone, where clearing is free and one repeated call away.
                if _conversation_size(messages) > _COMPACT_CAP:
                    messages = await _compact(spec, ctx, bound, messages)
                request = bound.request(list(messages), tools=offered)
                response = await call_with_retry(spec, bound.provider, request, ctx)
                ctx.usage = ctx.usage.merge(response.usage)
                ctx.emit(
                    "node_turn",
                    node_id=spec.id,
                    turn=turns,
                    text=_clip(response.text),
                    thinking=_clip(response.meta.get("thinking") or ""),
                    tool_call_count=len(response.tool_calls),
                )

                # A turn the model was cut off in the middle of is not an
                # answer, and it arrives looking exactly like one: the loop
                # ends on a turn with no tool calls, and a truncated turn has
                # none. Half a sentence then becomes the node's output and the
                # run reports success. The endpoint says so plainly --
                # OpenAI-shaped ones `length`, Anthropic `max_tokens` -- and it
                # was already being carried this far unread.
                if response.stop_reason in _CUT_OFF:
                    raise NodeError(
                        f"node '{spec.id}' was cut off before it finished: the "
                        f"model reached its output limit mid-turn",
                        node_id=spec.id,
                    )

                # No executor means none were offered, so a tool call here is
                # a model inventing one. There is nothing to run it with, and
                # the answer it gave is still an answer.
                if not response.tool_calls or executor is None:
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

        # `response` is deliberately the loop's last one, read after the
        # executor has closed: the turn that answered without a tool call.
        return _finish(
            spec, ctx, bound, response, turns=turns, tool_calls=tool_call_count
        )


def _workdir_for(spec: NodeSpec, ctx: RunContext, scope: dict[str, Any]) -> Path:
    """Where this node's commands run: its own `workdir`, else the task's.

    Physical, so the logical layer may leave it open and the task supply it --
    `preflight()` is where "nowhere to work" fails, before a token is spent.
    """
    workdir = (
        Path(_rendered(spec, spec.workdir, scope)).expanduser()
        if spec.workdir
        else ctx.workdir
    )
    if workdir is None:  # preflight should have caught this
        raise NodeError(f"node '{spec.id}': no workdir", node_id=spec.id)
    if not workdir.is_dir():
        raise NodeError(
            f"node '{spec.id}': workdir does not exist: {workdir}", node_id=spec.id
        )
    return workdir


class CommandNode(Node):
    """Runs one command and reports what it did. Calls no model.

    The exit code lands in scope as the **number the process returned**, so a
    router branches on the fact rather than on a model's account of it. That is
    the whole of it: the machine already knew, and asking a model to read a
    hundred lines of output and say "it passed" adds a turn and a way to be
    wrong.

    A non-zero exit is **not** a failed run. A red test suite is what the graph
    exists to react to; the run fails only when the command could not run at
    all -- a timeout, a missing program -- because "this did not start" and
    "this went red" are different facts.
    """

    async def run(self, ctx: RunContext) -> NodeResult:
        spec = self.spec
        workdir = _workdir_for(spec, ctx, ctx.scope())

        # Through the seam, never a bare subprocess: a task that asked to be
        # fenced is fenced here too.
        scope = ctx.scope()
        if spec.script is not None:
            # The code never passes through a shell: the interpreter reads it
            # from stdin, so a quote, a colon or a newline in it means what it
            # says rather than something to the shell on the way past.
            command = " ".join(LANGUAGES[spec.language or ""])
            stdin = _rendered(spec, spec.script, scope)
        else:
            command = _rendered(spec, spec.command or "", scope)
            stdin = None

        async with make_executor(workdir, ["shell"], ctx.tool_context) as executor:
            started = time.monotonic()
            try:
                result = await executor.run_command(
                    command,
                    timeout=spec.timeout,
                    env=spec.env or None,
                    stdin=stdin,
                )
            except ToolError as exc:
                # It never ran. That is the node failing, unlike an exit code.
                raise NodeError(f"node '{spec.id}': {exc}", node_id=spec.id) from exc

        output = {"exit_code": result.exit_code, "output": result.output}
        if spec.output.format == "json":
            # Only the text is a candidate for parsing; the code is already one.
            output["output"] = shape_output(spec, result.output)
        ctx.record_output(spec.id, output, spec.output.as_)
        if spec.output.into_state:
            ctx.state[spec.output.into_state] = unwrap(output)

        return NodeResult(
            node_id=spec.id,
            next_node=spec.next,
            output=output,
            meta={
                "command": spec.command,
                "exit_code": result.exit_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
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
    "agent": AgentNode,
    "command": CommandNode,
    "router": RouterNode,
}


def build_node(spec: NodeSpec) -> Node:
    cls = NODE_TYPES.get(spec.type)
    if cls is None:  # pragma: no cover - the schema rejects unknown types first
        raise NodeError(f"unknown node type '{spec.type}'", node_id=spec.id)
    return cls(spec)
