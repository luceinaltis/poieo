"""Local inference backends: OpenAI-compatible servers and Ollama.

These speak their own native HTTP APIs over httpx. (The Claude backend lives in
``anthropic_provider`` and uses the official SDK -- the two are never mixed.)
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from ..binding import ProviderSpec
from ..errors import ProviderError
from .base import (
    LLMRequest,
    LLMResponse,
    Provider,
    ToolCall,
    ToolDef,
    Usage,
    credential_for,
)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _wire_tools(tools: list[ToolDef]) -> list[dict[str, Any]]:
    """Both local APIs take the OpenAI-style function wrapper."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _translate_history(request: LLMRequest, arguments_as_json: bool) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    for message in request.messages:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                arguments = call["arguments"]
                calls.append(
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(arguments)
                            if arguments_as_json
                            else arguments,
                        },
                    }
                )
            messages.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
        else:
            messages.append(dict(message))
    return messages


def _openai_messages(request: LLMRequest) -> list[dict[str, Any]]:
    return _translate_history(request, arguments_as_json=True)


def _ollama_messages(request: LLMRequest) -> list[dict[str, Any]]:
    return _translate_history(request, arguments_as_json=False)


class _HttpProvider(Provider):
    """Shared httpx plumbing for the local backends."""

    def __init__(self, name: str, spec: ProviderSpec):
        super().__init__(name, spec)
        headers = {"content-type": "application/json"}
        key = credential_for(name, spec)
        if key:
            headers["authorization"] = f"Bearer {key}"
        self.client = httpx.AsyncClient(
            base_url=(spec.base_url or "").rstrip("/"),
            timeout=spec.timeout,
            headers=headers,
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self.client.post(path, json=payload)
        except httpx.RequestError as exc:
            raise ProviderError(
                f"{self.name}: cannot reach {self.spec.base_url}: {exc}",
                provider=self.name,
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}: {response.text[:400]}",
                provider=self.name,
                retryable=response.status_code in _RETRYABLE_STATUS,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(
                f"{self.name}: response was not JSON: {response.text[:200]}",
                provider=self.name,
            ) from exc

    async def _list_health(self, path: str, key: str, field: str) -> tuple[bool, str]:
        """Is the server there, and what has it got?

        Both local backends answer with a list of models and differ only in
        the path and the key names. Every outcome is a return value, never an
        exception -- including a 200 that is not JSON, which is what a proxy
        or a captive portal answers with.
        """
        try:
            response = await self.client.get(path)
        except httpx.RequestError as exc:
            return False, f"unreachable: {exc}"
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}"
        try:
            listed = response.json().get(key) or []
        except ValueError:
            return False, f"reachable, but the answer was not JSON: {response.text[:80]}"
        names = [str(entry.get(field)) for entry in listed if entry.get(field)]
        return True, f"reachable ({', '.join(names[:5]) or 'no models'})"

    async def aclose(self) -> None:
        await self.client.aclose()


class OpenAICompatibleProvider(_HttpProvider):
    """vLLM, SGLang, llama.cpp server, LM Studio, TGI -- anything exposing /v1."""

    type = "openai_compatible"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        params = dict(request.params)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": _openai_messages(request),
            "stream": False,
        }
        if "max_tokens" in params:
            payload["max_tokens"] = params.pop("max_tokens")
        payload.update(params)
        if request.tools:
            payload["tools"] = _wire_tools(request.tools)

        data = await self._post("/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                f"{self.name}: response contained no choices", provider=self.name
            )
        message = choices[0].get("message") or {}
        tool_calls = []
        for call in (message.get("tool_calls") or []):
            raw = call["function"].get("arguments") or "{}"
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"{self.name}: model produced malformed tool arguments: {raw[:200]}",
                    provider=self.name,
                    retryable=True,
                ) from exc
            tool_calls.append(
                ToolCall(
                    id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                    name=call["function"]["name"],
                    arguments=arguments,
                )
            )
        usage = data.get("usage") or {}
        return LLMResponse(
            text=message.get("content") or "",
            model=data.get("model", request.model),
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0) or 0,
                output_tokens=usage.get("completion_tokens", 0) or 0,
            ),
            stop_reason=choices[0].get("finish_reason"),
            tool_calls=tool_calls,
        )

    async def health(self) -> tuple[bool, str]:
        return await self._list_health("/models", key="data", field="id")


class OllamaProvider(_HttpProvider):
    """Ollama's native /api/chat endpoint."""

    type = "ollama"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        params = dict(request.params)
        options: dict[str, Any] = dict(params.pop("options", {}) or {})
        # Map the harness's neutral names onto Ollama's `options` block.
        if "max_tokens" in params:
            options["num_predict"] = params.pop("max_tokens")
        for key in ("temperature", "top_p", "top_k", "seed", "stop"):
            if key in params:
                options[key] = params.pop(key)

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": _ollama_messages(request),
            "stream": False,
        }
        if options:
            payload["options"] = options
        payload.update(params)
        if request.tools:
            payload["tools"] = _wire_tools(request.tools)

        data = await self._post("/api/chat", payload)
        message = data.get("message") or {}
        tool_calls = [
            ToolCall(
                id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=call["function"]["name"],
                arguments=dict(call["function"].get("arguments") or {}),
            )
            for call in (message.get("tool_calls") or [])
        ]
        meta: dict[str, Any] = {}
        if message.get("thinking"):
            meta["thinking"] = message["thinking"]
        return LLMResponse(
            text=message.get("content") or "",
            model=data.get("model", request.model),
            usage=Usage(
                input_tokens=data.get("prompt_eval_count", 0) or 0,
                output_tokens=data.get("eval_count", 0) or 0,
            ),
            stop_reason=data.get("done_reason"),
            tool_calls=tool_calls,
            meta=meta,
        )

    async def health(self) -> tuple[bool, str]:
        return await self._list_health("/api/tags", key="models", field="name")
