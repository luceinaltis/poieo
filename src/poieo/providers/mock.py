"""A deterministic in-process provider for tests and dry runs.

Declare it in a binding to exercise a graph's wiring without spending tokens:

    providers:
      fake:
        type: mock
        options:
          responses:
            classifier: "bug"     # keyed by role, or "*" for a catch-all
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ..binding import ProviderSpec
from ..errors import ProviderError
from .base import LLMRequest, LLMResponse, Provider, ToolCall, Usage


def _roughly(request: LLMRequest) -> int:
    """About how many tokens this request carries.

    Four characters to a token, over everything that goes on the wire: the
    system block, every message, and the tool definitions, which are not free
    and are sent again on every turn.
    """
    total = len(request.system or "")
    for message in request.messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        calls = message.get("tool_calls")
        if calls:
            total += len(json.dumps(calls, ensure_ascii=False, default=str))
    for tool in request.tools or []:
        total += len(tool.name) + len(tool.description)
        total += len(json.dumps(tool.input_schema, ensure_ascii=False, default=str))
    return total // 4


class MockProvider(Provider):
    type = "mock"

    def __init__(self, name: str, spec: ProviderSpec):
        super().__init__(name, spec)
        options: dict[str, Any] = spec.options or {}
        self.responses: dict[str, Any] = options.get("responses", {})
        self.fallback: str = options.get("fallback", "")
        # Seconds to spend on each call. A model takes time, and a mock that
        # answers instantly makes every observation surface look idle.
        self.latency: float = float(options.get("latency", 0) or 0)
        # Every request, in order -- assertions in tests read this.
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.latency:
            await asyncio.sleep(self.latency)
        key = request.role or request.model
        value = self.responses.get(key, self.responses.get("*", self.fallback))
        if isinstance(value, list):
            # A list is a script: one entry per call to this role.
            index = sum(1 for c in self.calls if (c.role or c.model) == key)
            if not value:
                raise ProviderError(f"mock '{self.name}': empty script", provider=self.name)
            value = value[min(index - 1, len(value) - 1)]
        tool_calls: list[ToolCall] = []
        text = ""
        stop: str | None = None
        meta: dict[str, Any] = {}
        if isinstance(value, dict):
            # A dict entry scripts an assistant turn that may request tools.
            text = value.get("text", "")
            calls = value.get("tool_calls", [])
            for i, call in enumerate(calls, start=1):
                # One call keeps the bare id; several are suffixed, so a
                # transcript can be read without counting brackets.
                suffix = "" if len(calls) == 1 else f"_{i}"
                tool_calls.append(
                    ToolCall(
                        id=f"mock_{len(self.calls)}{suffix}",
                        name=call["name"],
                        arguments=dict(call.get("arguments", {})),
                    )
                )
            if "raw_content" in value:
                # Lets a test exercise the raw_content passthrough seam
                # (AgentNode carrying it, providers ignoring it) without a
                # real provider.
                meta["raw_content"] = value["raw_content"]
            if value.get("thinking"):
                meta["thinking"] = value["thinking"]
            # Lets a test script a turn the model was cut off in the middle of,
            # which is a thing real endpoints do and nothing else here can fake.
            if value.get("stop_reason"):
                stop = str(value["stop_reason"])
        else:
            text = value if isinstance(value, str) else str(value)
        return LLMResponse(
            text=text,
            model=request.model,
            usage=Usage(
                # Roughly what was sent, rather than a flat zero. A real
                # endpoint counts its input, and code that decides anything
                # from that count -- how full the window is, what a run cost --
                # could not be exercised against a provider that always
                # answered nothing. Four characters to a token is the usual
                # rule of thumb and near enough for a mock.
                input_tokens=_roughly(request),
                output_tokens=len(text.split()),
            ),
            stop_reason=stop or ("tool_use" if tool_calls else "end_turn"),
            meta=meta,
            tool_calls=tool_calls,
        )

    async def health(self) -> tuple[bool, str]:
        return True, f"mock provider ({len(self.responses)} scripted role(s))"
