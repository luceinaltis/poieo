"""Claude API backend, via the official ``anthropic`` SDK."""

from __future__ import annotations

import os
from typing import Any

import anthropic

from ..binding import ProviderSpec
from ..errors import ProviderError
from .base import LLMRequest, LLMResponse, Provider, ToolCall, ToolDef, Usage

# Model families that take `thinking: {type: "adaptive"}`. Older models use the
# removed `budget_tokens` form, so we omit `thinking` for them entirely rather
# than send a shape the API will reject.
_ADAPTIVE_THINKING = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)

# Models that accept `output_config.effort`.
_EFFORT_MODELS = _ADAPTIVE_THINKING + ("claude-opus-4-5",)

# Sampling parameters were removed on these families; sending them is a 400.
_NO_SAMPLING = _ADAPTIVE_THINKING

_SAMPLING_KEYS = ("temperature", "top_p", "top_k")

# Streaming keeps large max_tokens from tripping the SDK's HTTP timeout, so the
# provider always streams and collects the final message.
_DEFAULT_MAX_TOKENS = 16000


def _matches(model: str, families: tuple[str, ...]) -> bool:
    return any(model.startswith(f) for f in families)


def _anthropic_tools(tools: list[ToolDef]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Neutral history -> Anthropic content blocks.

    Consecutive tool turns collapse into one user message: the API expects
    every tool_result for a turn's tool_use blocks together.
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            content: list[dict[str, Any]] = []
            if message.get("content"):
                content.append({"type": "text", "text": message["content"]})
            for call in message["tool_calls"]:
                content.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["name"],
                        "input": call["arguments"],
                    }
                )
            out.append({"role": "assistant", "content": content})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message["tool_call_id"],
                "content": message["content"],
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append(dict(message))
    return out


class AnthropicProvider(Provider):
    type = "anthropic"

    def __init__(self, name: str, spec: ProviderSpec):
        super().__init__(name, spec)
        kwargs: dict[str, Any] = {
            "timeout": spec.timeout,
            "max_retries": spec.max_retries,
        }
        if spec.base_url:
            kwargs["base_url"] = spec.base_url
        if spec.api_key_env:
            key = os.environ.get(spec.api_key_env)
            if not key:
                raise ProviderError(
                    f"provider '{name}': ${spec.api_key_env} is not set",
                    provider=name,
                )
            kwargs["api_key"] = key
        # With no explicit key the SDK resolves ANTHROPIC_API_KEY, an auth token,
        # or an `ant auth login` profile on its own.
        self.client = anthropic.AsyncAnthropic(**kwargs)
        self.warnings: list[str] = []

    def _build_kwargs(self, request: LLMRequest) -> dict[str, Any]:
        params = dict(request.params)
        model = request.model
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": int(params.pop("max_tokens", _DEFAULT_MAX_TOKENS)),
            "messages": _anthropic_messages(request.messages),
        }
        if request.system:
            kwargs["system"] = request.system

        if request.tools:
            kwargs["tools"] = _anthropic_tools(request.tools)

        # --- thinking -------------------------------------------------------
        thinking = params.pop("thinking", "auto")
        if _matches(model, _ADAPTIVE_THINKING):
            if thinking in ("auto", "adaptive", True):
                kwargs["thinking"] = {"type": "adaptive"}
            elif thinking in ("summarized",):
                kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
            elif thinking in ("off", "disabled", False):
                kwargs["thinking"] = {"type": "disabled"}
            elif isinstance(thinking, dict):
                kwargs["thinking"] = thinking
        elif thinking not in ("auto", "off", "disabled", False, None):
            self._warn(f"model '{model}' does not support adaptive thinking; ignoring")

        # --- effort ---------------------------------------------------------
        output_config: dict[str, Any] = dict(params.pop("output_config", {}) or {})
        effort = params.pop("effort", None)
        if effort:
            if _matches(model, _EFFORT_MODELS):
                output_config["effort"] = effort
            else:
                self._warn(f"model '{model}' does not support effort; ignoring")
        # Disabled thinking is only accepted at effort high or below.
        if (
            kwargs.get("thinking", {}).get("type") == "disabled"
            and output_config.get("effort") in {"xhigh", "max"}
        ):
            raise ProviderError(
                f"model '{model}': thinking cannot be disabled at effort "
                f"'{output_config['effort']}'",
                provider=self.name,
            )
        if output_config:
            kwargs["output_config"] = output_config

        # --- sampling -------------------------------------------------------
        for key in _SAMPLING_KEYS:
            if key in params:
                value = params.pop(key)
                if _matches(model, _NO_SAMPLING):
                    self._warn(f"model '{model}' rejects {key}; dropping it")
                else:
                    kwargs[key] = value

        if "cache_control" in params:
            kwargs["cache_control"] = params.pop("cache_control")
        if "stop_sequences" in params:
            kwargs["stop_sequences"] = params.pop("stop_sequences")

        # Anything left over is passed straight through, so a new API parameter
        # is usable from a binding file without a code change here.
        kwargs.update(params)
        return kwargs

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        kwargs = self._build_kwargs(request)
        try:
            async with self.client.messages.stream(**kwargs) as stream:
                message = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"{self.name}: HTTP {exc.status_code}: {exc.message}",
                provider=self.name,
                retryable=exc.status_code == 429 or exc.status_code >= 500,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(
                f"{self.name}: connection error: {exc}", provider=self.name, retryable=True
            ) from exc

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            raise ProviderError(
                f"{self.name}: model declined the request (category={category})",
                provider=self.name,
            )

        text = "".join(b.text for b in message.content if b.type == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in message.content
            if b.type == "tool_use"
        ]
        usage = message.usage
        return LLMResponse(
            text=text,
            model=message.model,
            usage=Usage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            ),
            stop_reason=message.stop_reason,
            meta={"message_id": message.id},
            tool_calls=tool_calls,
        )

    async def health(self) -> tuple[bool, str]:
        try:
            models = await self.client.models.list(limit=1)
        except anthropic.AuthenticationError:
            return False, "authentication failed (no usable API key or profile)"
        except anthropic.APIError as exc:
            return False, f"unreachable: {exc}"
        count = len(models.data)
        return True, f"reachable ({count} model(s) visible)"

    async def aclose(self) -> None:
        await self.client.close()
