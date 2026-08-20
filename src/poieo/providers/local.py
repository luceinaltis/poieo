"""Local inference backends: OpenAI-compatible servers and Ollama.

These speak their own native HTTP APIs over httpx. (The Claude backend lives in
``anthropic_provider`` and uses the official SDK -- the two are never mixed.)
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..binding import ProviderSpec
from ..errors import ProviderError
from .base import LLMRequest, LLMResponse, Provider, Usage

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class _HttpProvider(Provider):
    """Shared httpx plumbing for the local backends."""

    def __init__(self, name: str, spec: ProviderSpec):
        super().__init__(name, spec)
        headers = {"content-type": "application/json"}
        if spec.api_key_env:
            key = os.environ.get(spec.api_key_env)
            if not key:
                raise ProviderError(
                    f"provider '{name}': ${spec.api_key_env} is not set", provider=name
                )
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

    @staticmethod
    def _with_system(request: LLMRequest) -> list[dict[str, Any]]:
        """Local chat APIs carry the system prompt as the first message."""
        if not request.system:
            return list(request.messages)
        return [{"role": "system", "content": request.system}, *request.messages]

    async def aclose(self) -> None:
        await self.client.aclose()


class OpenAICompatibleProvider(_HttpProvider):
    """vLLM, SGLang, llama.cpp server, LM Studio, TGI -- anything exposing /v1."""

    type = "openai_compatible"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        params = dict(request.params)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": self._with_system(request),
            "stream": False,
        }
        if "max_tokens" in params:
            payload["max_tokens"] = params.pop("max_tokens")
        payload.update(params)

        data = await self._post("/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                f"{self.name}: response contained no choices", provider=self.name
            )
        message = choices[0].get("message") or {}
        usage = data.get("usage") or {}
        return LLMResponse(
            text=message.get("content") or "",
            model=data.get("model", request.model),
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0) or 0,
                output_tokens=usage.get("completion_tokens", 0) or 0,
            ),
            stop_reason=choices[0].get("finish_reason"),
        )

    async def health(self) -> tuple[bool, str]:
        try:
            response = await self.client.get("/models")
        except httpx.RequestError as exc:
            return False, f"unreachable: {exc}"
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}"
        names = [m.get("id") for m in (response.json().get("data") or [])]
        return True, f"reachable ({', '.join(filter(None, names[:5])) or 'no models'})"


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
            "messages": self._with_system(request),
            "stream": False,
        }
        if options:
            payload["options"] = options
        payload.update(params)

        data = await self._post("/api/chat", payload)
        message = data.get("message") or {}
        return LLMResponse(
            text=message.get("content") or "",
            model=data.get("model", request.model),
            usage=Usage(
                input_tokens=data.get("prompt_eval_count", 0) or 0,
                output_tokens=data.get("eval_count", 0) or 0,
            ),
            stop_reason=data.get("done_reason"),
        )

    async def health(self) -> tuple[bool, str]:
        try:
            response = await self.client.get("/api/tags")
        except httpx.RequestError as exc:
            return False, f"unreachable: {exc}"
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}"
        names = [m.get("name") for m in (response.json().get("models") or [])]
        return True, f"reachable ({', '.join(filter(None, names[:5])) or 'no models'})"
