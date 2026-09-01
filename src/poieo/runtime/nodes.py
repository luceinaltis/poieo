"""Node implementations. One class per ``NodeSpec.type``."""

from __future__ import annotations

import abc
import asyncio
import copy
import json
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..binding import ResolvedModel
from ..errors import ExpressionError, NodeError, ProviderError, RunAborted
from ..expr import evaluate, render, unwrap
from ..graph import NodeSpec
from ..providers import LLMRequest, LLMResponse
from ..providers.base import Hands, ToolCall, ToolDef
from ..tools import Executor, ToolError, is_compiled, make_executor
from .context import NodeResult, RunContext

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class Node(abc.ABC):
    """Base class; register subclasses in :data:`NODE_TYPES`."""

    def __init__(self, spec: NodeSpec):
        self.spec = spec

    @abc.abstractmethod
    async def run(self, ctx: RunContext) -> NodeResult: ...


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
                    f"node '{spec.id}': output path '{out.path}' is missing from the parsed JSON",
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


# Display metadata lives in the model-facing schema, so reserve its name: a
# tool is otherwise allowed to have a real `purpose` argument of its own.
_ACTIVITY_PURPOSE = "__poieo_activity_purpose"
_ACTIVITY_PURPOSE_DESCRIPTION = (
    "One short sentence for the person watching this run: what this call is "
    "about to accomplish and why it helps the current task. Describe the "
    "purpose, not the tool mechanics or private reasoning."
)


def _tools_with_activity_purpose(tools: list[ToolDef]) -> list[ToolDef]:
    """Ask every tool call to carry the sentence its activity row will lead with.

    The executor's definitions are shared objects, so the display-only field is
    added to copies. It is removed again before execution; a tool should never
    have to know how the board explains it.
    """
    offered: list[ToolDef] = []
    for tool in tools:
        schema = copy.deepcopy(tool.input_schema)
        properties = dict(schema.get("properties") or {})
        properties[_ACTIVITY_PURPOSE] = {
            "type": "string",
            "description": _ACTIVITY_PURPOSE_DESCRIPTION,
        }
        schema["properties"] = properties
        required = list(schema.get("required") or [])
        if _ACTIVITY_PURPOSE not in required:
            required.append(_ACTIVITY_PURPOSE)
        schema["required"] = required
        offered.append(
            ToolDef(
                name=tool.name,
                description=tool.description,
                input_schema=schema,
            )
        )
    return offered


# How large a conversation may get before its older observations are dropped,
# in characters -- the unit the tools already measure their own output in
# (`_READ_CAP`, `_OUTPUT_CAP`), and one that needs no tokenizer to read.
_CONTEXT_CAP = 120_000
# How many of the most recent tool results survive a clearing, whole.
_KEEP_RESULTS = 3
# The share of a model's window at which each of the two caps fires, for a
# binding that says how much its model holds. Anthropic's own defaults are the
# same shape -- clear at 100k of a 200k window, compact at 180k.
_CLEAR_AT = 0.5
_COMPACT_AT = 0.9
_CLEARED = "[cleared to save room -- call the tool again if you still need this]"
# For the one result that clearing cannot reach: bigger than the window on its
# own, so no amount of dropping what came before it helps. Says what to do
# rather than only that something is gone.
_TOO_BIG = "[this did not fit in the model's context -- fetch it in pieces instead. read_file takes offset and limit]"


def _drop_newest_result(messages: list[dict[str, Any]]) -> int:
    """Replace the most recent tool result, which clearing always keeps.

    `_clear_old_results` protects the last few on purpose, and that is right
    until one of them is by itself larger than the window: then every clearing
    and every retry leaves it in place and fails again. Only called once the
    endpoint has *shown* that what we sent did not fit -- before that it would
    be a guess, and a guess that made the tool call pointless would have the
    model read the same file forever.
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str) or content in (_CLEARED, _TOO_BIG):
            return 0
        messages[index] = {**message, "content": _TOO_BIG}
        return len(content) - len(_TOO_BIG)
    return 0


def _too_big(
    window: int | None,
    sent: int,
    messages: list[dict[str, Any]],
    share: float,
    cap: int,
) -> bool:
    """Whether the conversation has grown past a threshold.

    Two readings of the same question, and the first is the real one. When the
    binding says how much the model holds, `sent` is what the endpoint counted
    the last request at -- a measurement, not an estimate, and free because it
    arrives on every response. Where nobody has said, the character count is
    what this loop had before anyone could.

    The difference is not academic. `_CONTEXT_CAP` is 2.3% of what
    `z-ai/glm-5.3-flash` holds and 11.4% of a local qwen3.5; a step was watched
    re-reading one file eight times because its history was emptied at a
    fortieth of what the model could carry.

    `sent` lags by a turn -- it describes the request before this one. That is
    what a threshold on a measurement costs, and it is the same lag Anthropic's
    server-side trigger has.
    """
    if window:
        return sent > window * share
    return _conversation_size(messages) > cap


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
    freed = before - _conversation_size(folded)
    if freed <= 0:
        # A summary longer than what it replaced is not a summary. Watched in
        # another harness: a compression pass took a conversation from 64,186
        # tokens to 71,173 -- fourteen messages in, fourteen out, seven
        # thousand tokens larger -- and reported it as done. Rebuilding is not
        # shrinking, and the model was asked to be brief rather than made to
        # be, so this is checked rather than assumed.
        ctx.emit(
            "node_compact_failed",
            node_id=spec.id,
            error=f"the summary was longer than the turns it would have replaced ({-freed} characters longer)",
        )
        return messages
    ctx.emit("node_compacted", node_id=spec.id, folded=freed, kept=_KEEP_TURNS)
    return folded


@dataclass(slots=True)
class _AgentLoop:
    """One agent node's conversation, tools, and turn accounting.

    ``AgentNode`` owns setup and teardown. This object owns the state that
    changes between model calls, so each transition has one place to update it.
    """

    spec: NodeSpec
    ctx: RunContext
    bound: _Bound
    workdir: Path | None
    toolsets: tuple[str, ...]
    executor: Executor | None
    messages: list[dict[str, Any]] = field(init=False)
    offered_tools: list[ToolDef] = field(init=False)
    turns: int = field(init=False, default=0)
    tool_call_count: int = field(init=False, default=0)
    # Which tools, and how many times each. Only read when the node runs out of
    # turns, where the counts distinguish productive work from repeated reads.
    reached_for: dict[str, int] = field(init=False, default_factory=dict)
    sent_tokens: int = field(init=False, default=0)
    retried_smaller: bool = field(init=False, default=False)
    context_shrank: bool = field(init=False, default=False)
    expires_at: float | None = field(init=False)

    def __post_init__(self) -> None:
        self.messages = [{"role": "user", "content": self.bound.prompt}]
        definitions = self.executor.definitions() if self.executor is not None else []
        self.offered_tools = _tools_with_activity_purpose(definitions)

        # Checked at the top of a turn rather than raced against the model
        # call: a request already sent is paid for whether its answer is kept.
        self.expires_at = time.monotonic() + self.spec.deadline if self.spec.deadline else None

    def _hands(self) -> Hands | None:
        # Only a provider that runs its own tool loop reads this, and only a
        # node with tools has anything to lend. Built per request rather than
        # stored here: its bound ``run`` method points back to this loop, and
        # storing both sides would keep the finished conversation in a cycle.
        return (
            Hands(
                run=self._execute_tool,
                workdir=str(self.workdir) if self.workdir else None,
                max_turns=self.spec.max_turns,
                toolsets=self.toolsets,
                boxed=bool(self.ctx.tool_context and self.ctx.tool_context.isolation),
            )
            if self.executor is not None
            else None
        )

    def _start_turn(self) -> None:
        if self.ctx.cancel is not None and self.ctx.cancel.is_set():
            raise RunAborted(f"cancelled during agent node '{self.spec.id}'")
        if self.expires_at is not None and time.monotonic() >= self.expires_at:
            raise NodeError(
                f"node '{self.spec.id}' passed its deadline ({self.spec.deadline}s) after {self.turns} turn(s)",
                node_id=self.spec.id,
            )
        self.turns += 1

    async def _make_context_room(self, window: int | None) -> None:
        # Only past the cap, and then all at once. Clearing on every turn would
        # move the cached prompt prefix on every turn too.
        if _too_big(window, self.sent_tokens, self.messages, _CLEAR_AT, _CONTEXT_CAP):
            freed = _clear_old_results(self.messages)
            if freed:
                self.context_shrank = True
                self.ctx.emit(
                    "node_context_cleared",
                    node_id=self.spec.id,
                    turn=self.turns,
                    freed=freed,
                    kept=_KEEP_RESULTS,
                )
        # Clearing is free and reversible, so folding follows only when that
        # was not enough; a summary costs a model call and cannot be undone.
        if _too_big(window, self.sent_tokens, self.messages, _COMPACT_AT, _COMPACT_CAP):
            before_fold = len(self.messages)
            self.messages = await _compact(self.spec, self.ctx, self.bound, self.messages)
            self.context_shrank = self.context_shrank or len(self.messages) != before_fold

    def _request(self) -> LLMRequest:
        return self.bound.request(
            list(self.messages),
            tools=self.offered_tools,
            hands=self._hands(),
        )

    async def _ask_model(self) -> LLMResponse:
        request = self._request()
        try:
            return await call_with_retry(self.spec, self.bound.provider, request, self.ctx)
        except NodeError:
            # Retry once with fewer bytes, but only when there was something to
            # clear. Error text is deliberately not classified by backend.
            freed = 0 if self.retried_smaller else _clear_old_results(self.messages)
            if not freed:
                raise
            self.retried_smaller = True
            self.context_shrank = True
            self.ctx.emit(
                "node_retried_smaller",
                node_id=self.spec.id,
                turn=self.turns,
                freed=freed,
                kept=_KEEP_RESULTS,
            )
            return await call_with_retry(
                self.spec,
                self.bound.provider,
                self._request(),
                self.ctx,
            )

    def _record_response(self, response: LLMResponse) -> None:
        # What the endpoint says it charged wins; declared prices fill silence.
        if response.usage.cost is None and self.bound.resolved.prices is not None:
            response.usage.cost = self.bound.resolved.prices.charge(response.usage)
        received_tokens = response.usage.input_tokens

        # A conversation only grows unless this loop shrank it. A non-growing
        # endpoint count therefore means the endpoint silently dropped input.
        if self.sent_tokens and received_tokens and received_tokens <= self.sent_tokens and not self.context_shrank:
            # Oldest first. Only when nothing old remains is the newest result
            # replaced, and only after the endpoint has shown it did not fit.
            freed, note = _clear_old_results(self.messages), ""
            if not freed:
                freed = _drop_newest_result(self.messages)
                note = _TOO_BIG if freed else ""
            self.ctx.emit(
                "node_input_dropped",
                node_id=self.spec.id,
                turn=self.turns,
                before=self.sent_tokens,
                kept=received_tokens,
                freed=freed,
                note=note,
            )
            if not freed:
                raise NodeError(
                    f"node '{self.spec.id}': the endpoint kept {received_tokens} tokens of a "
                    f"conversation it was sent more of, and there is nothing left to drop "
                    f"-- its window is smaller than this step needs",
                    node_id=self.spec.id,
                )

        self.context_shrank = False
        self.sent_tokens = received_tokens
        self.ctx.usage = self.ctx.usage.merge(response.usage)
        self.ctx.emit(
            "node_turn",
            node_id=self.spec.id,
            turn=self.turns,
            text=_clip(response.text),
            thinking=_clip(response.meta.get("thinking") or ""),
            tool_call_count=len(response.tool_calls),
            # The run carries one total; only this pair can show whether a
            # model writes more as the conversation it reads grows.
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_tokens,
        )

    def _require_another_turn(self) -> None:
        if self.turns < self.spec.max_turns:
            return
        spent = ", ".join(
            f"{name} {count}x" for name, count in sorted(self.reached_for.items(), key=lambda pair: -pair[1])
        )
        raise NodeError(
            f"node '{self.spec.id}' hit max_turns ({self.spec.max_turns}) "
            f"with tool calls still pending; it spent them on {spent or 'nothing'}",
            node_id=self.spec.id,
        )

    async def _execute_tool(self, call: ToolCall) -> tuple[str, bool]:
        """Run and record one call, whoever owns the surrounding tool loop."""
        if self.executor is None:  # Hands is never built in this state.
            raise NodeError(f"node '{self.spec.id}': no executor for tool call", node_id=self.spec.id)
        arguments = dict(call.arguments)
        raw_purpose = arguments.pop(_ACTIVITY_PURPOSE, "")
        purpose = raw_purpose.strip() if isinstance(raw_purpose, str) else ""
        executable = ToolCall(id=call.id, name=call.name, arguments=arguments)
        started = time.monotonic()
        result = await self.executor.execute(executable)
        self.tool_call_count += 1
        self.reached_for[call.name] = self.reached_for.get(call.name, 0) + 1
        self.ctx.emit(
            "node_tool_call",
            node_id=self.spec.id,
            turn=self.turns,
            name=call.name,
            purpose=_clip(purpose, 240) if purpose else "",
            arguments=_clip(arguments),
            result=_clip(result.text),
            error=result.error,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return result.text, result.error

    async def _append_tool_results(self, response: LLMResponse) -> None:
        assistant_turn: dict[str, Any] = {
            "role": "assistant",
            "content": response.text,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments} for call in response.tool_calls
            ],
        }
        raw_content = response.meta.get("raw_content")
        if raw_content:
            # Provider-specific blocks (for example, Anthropic thinking) must
            # be replayed verbatim; other providers ignore the key.
            assistant_turn["raw_content"] = raw_content
        self.messages.append(assistant_turn)
        for call in response.tool_calls:
            text, _failed = await self._execute_tool(call)
            self.messages.append({"role": "tool", "tool_call_id": call.id, "content": text})

    async def run(self) -> LLMResponse:
        # The binding's deliberate limit wins. Otherwise ask the endpoint once;
        # providers remember the answer, and character caps remain the fallback.
        window = self.bound.resolved.context
        if window is None:
            window = await self.bound.provider.context_for(self.bound.resolved.model)

        while True:
            self._start_turn()
            await self._make_context_room(window)
            response = await self._ask_model()
            self._record_response(response)

            # A truncated answer has the same no-tool-call shape as a finished
            # one, so the endpoint's stop reason must be checked first.
            if response.stop_reason in _CUT_OFF:
                raise NodeError(
                    f"node '{self.spec.id}' was cut off before it finished: "
                    "the model reached its output limit mid-turn",
                    node_id=self.spec.id,
                )
            # No executor means no tools were offered. An invented call cannot
            # be run, but the answer the model gave is still an answer.
            if not response.tool_calls or self.executor is None:
                return response

            self._require_another_turn()
            await self._append_tool_results(response)


class AgentNode(Node):
    """Renders a prompt, calls the model, and loops while it asks for tools.

    Tools are the whole of what varies here. A node that names none is shown
    none, so it cannot ask for one, so the loop runs once and returns --
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
        workdir = Path(_rendered(spec, spec.workdir, bound.scope)).expanduser() if spec.workdir else ctx.workdir
        if toolsets:
            if workdir is None:  # preflight should have caught this
                raise NodeError(f"node '{spec.id}': no workdir", node_id=spec.id)
            if not workdir.is_dir():
                raise NodeError(
                    f"node '{spec.id}': workdir does not exist: {workdir}",
                    node_id=spec.id,
                )

        # Nothing is built for a node with no tools: an executor can mean a
        # container, and standing one up to offer nothing would be pure cost.
        async with AsyncExitStack() as stack:
            executor = (
                await stack.enter_async_context(
                    make_executor(workdir, toolsets, ctx.tool_context)  # type: ignore[arg-type]
                )
                if toolsets
                else None
            )
            loop = _AgentLoop(
                spec=spec,
                ctx=ctx,
                bound=bound,
                workdir=workdir,
                toolsets=tuple(toolsets),
                executor=executor,
            )
            response = await loop.run()

        # The answering turn is finished only after the executor is closed.
        return _finish(
            spec,
            ctx,
            bound,
            response,
            turns=loop.turns,
            tool_calls=loop.tool_call_count,
        )


def _workdir_for(spec: NodeSpec, ctx: RunContext, scope: dict[str, Any]) -> Path:
    """Where this node's commands run: its own `workdir`, else the task's.

    Physical, so the logical layer may leave it open and the task supply it --
    `preflight()` is where "nowhere to work" fails, before a token is spent.
    """
    workdir = Path(_rendered(spec, spec.workdir, scope)).expanduser() if spec.workdir else ctx.workdir
    if workdir is None:  # preflight should have caught this
        raise NodeError(f"node '{spec.id}': no workdir", node_id=spec.id)
    if not workdir.is_dir():
        raise NodeError(f"node '{spec.id}': workdir does not exist: {workdir}", node_id=spec.id)
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
        # Rendered like the command and the script are. For a compiled script
        # this is the *only* way the run reaches the program, which is why it
        # is a template and the code is not.
        env = {k: _rendered(spec, v, scope) for k, v in spec.env.items()} or None

        async with make_executor(workdir, ["shell"], ctx.tool_context) as executor:
            started = time.monotonic()
            try:
                if spec.script is not None:
                    # A compiled script is a program, not a template: `{{` in
                    # it is the language's, and rendering would both mangle it
                    # and key the build cache on the run. Its varying part
                    # arrives through `env`, which is rendered below.
                    code = spec.script if is_compiled(spec.language or "") else _rendered(spec, spec.script, scope)
                    # Which interpreter, or which compiler and where its output
                    # is kept, is the executor's business: where a thing is
                    # built is where it has to run.
                    result = await executor.run_script(
                        spec.language or "",
                        code,
                        timeout=spec.timeout,
                        env=env,
                    )
                else:
                    result = await executor.run_command(
                        _rendered(spec, spec.command or "", scope),
                        timeout=spec.timeout,
                        env=env,
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


class ConfirmNode(Node):
    """Puts a question to a person, and ends the run there. Calls no model.

    The step nobody else can take. poieo's other safeguard is the worktree --
    the run works in a private copy and the morning accepts or discards the
    diff -- and that covers everything a run writes to a file. It does not
    cover what leaves the copy: a push, a merge, a deployment, an email, a
    charge. Discarding a worktree does not unsend a message.

    The run **ends** rather than suspending. Nothing is held open, no runner
    waits, and the answer arrives afterwards as one more fact about a finished
    run -- which is why what happens next is the card's `then:` and not a
    `next:` here. Suspending mid-walk would need the whole run's scope kept
    alive until morning, and would hold the task's only runner while it waited.
    """

    async def run(self, ctx: RunContext) -> NodeResult:
        spec = self.spec
        question = _rendered(spec, spec.prompt or "", ctx.scope())
        ctx.asked = {
            "node": spec.id,
            "question": question,
            "choices": list(spec.choices),
        }
        # The question, not the answer. The answer is a fact about the run and
        # lives in one place, `run.answer`; a second copy here would be a
        # second thing to keep true.
        ctx.record_output(spec.id, question, spec.output.as_)
        return NodeResult(
            node_id=spec.id,
            next_node=None,
            output=question,
            meta={"asked": True, "choices": list(spec.choices)},
        )


NODE_TYPES: dict[str, type[Node]] = {
    "agent": AgentNode,
    "command": CommandNode,
    "router": RouterNode,
    "confirm": ConfirmNode,
}


def build_node(spec: NodeSpec) -> Node:
    cls = NODE_TYPES.get(spec.type)
    if cls is None:  # pragma: no cover - the schema rejects unknown types first
        raise NodeError(f"unknown node type '{spec.type}'", node_id=spec.id)
    return cls(spec)
