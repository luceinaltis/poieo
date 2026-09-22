"""Local inference backends: OpenAI-compatible servers and Ollama.

These speak their own native HTTP APIs over httpx. (The Claude backend lives in
``anthropic_provider`` and uses the official SDK -- the two are never mixed.)
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..binding import ProviderSpec
from ..errors import ProviderError
from .base import (
    Delta,
    LLMRequest,
    LLMResponse,
    Provider,
    ToolCall,
    ToolDef,
    Usage,
    blocks_of,
    credential_for,
    text_of,
)

# 529 is in no RFC. Anthropic and TypeSafe both answer it for "overloaded",
# which is the server's mood rather than the request's shape, and worth a
# second try like a 503.
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


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


def _data_url(block: dict[str, Any]) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": f"data:{block['media_type']};base64,{block['data']}"}}


def _openai_content(message: dict[str, Any], held: list[dict[str, Any]]) -> dict[str, Any]:
    """A message whose content is blocks, in the OpenAI shape.

    A tool message here takes only text, so its pictures are put in `held`,
    to be shown as the next user message once the turn's results are all in.
    """
    content = message.get("content")
    if not isinstance(content, list):
        return dict(message)
    if message.get("role") == "tool":
        held.extend(_data_url(block) for block in content if block.get("type") == "image")
        return {**message, "content": text_of(content, picture="")}
    return {**message, "content": [_data_url(b) if b.get("type") == "image" else b for b in content]}


def _ollama_content(message: dict[str, Any]) -> dict[str, Any]:
    """A message whose content is blocks, in Ollama's shape: the words as the
    content and the pictures beside them, bare base64."""
    content = message.get("content")
    if not isinstance(content, list):
        return dict(message)
    images = [block["data"] for block in blocks_of(content) if block.get("type") == "image"]
    return {**message, "content": text_of(content, picture=""), **({"images": images} if images else {})}


def _translate_history(request: LLMRequest, arguments_as_json: bool) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    held: list[dict[str, Any]] = []
    for message in request.messages:
        if held and message.get("role") != "tool":
            messages.append({"role": "user", "content": held})
            held = []
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
                            "arguments": json.dumps(arguments) if arguments_as_json else arguments,
                        },
                    }
                )
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
        elif arguments_as_json:
            messages.append(_openai_content(message, held))
        else:
            messages.append(_ollama_content(message))
    if held:
        messages.append({"role": "user", "content": held})
    return messages


def _openai_messages(request: LLMRequest) -> list[dict[str, Any]]:
    return _translate_history(request, arguments_as_json=True)


def _ollama_messages(request: LLMRequest) -> list[dict[str, Any]]:
    return _translate_history(request, arguments_as_json=False)


def _check_embeddings(name: str, vectors: list[list[float]], expected: int) -> None:
    """One vector per input, all in the one space the endpoint named."""
    dimensions = {len(vector) for vector in vectors}
    finite = all(math.isfinite(value) for vector in vectors for value in vector)
    if len(vectors) != expected or dimensions == {0} or len(dimensions) != 1 or not finite:
        raise ProviderError(
            f"{name}: embedding response did not contain {expected} equal-sized vectors",
            provider=name,
        )


class _HttpProvider(Provider):
    """Shared httpx plumbing for the backends that speak plain HTTP: the local
    ones below, and TypeSafe's in ``typesafe``."""

    def __init__(self, name: str, spec: ProviderSpec):
        super().__init__(name, spec)
        headers = {"content-type": "application/json"}
        key = credential_for(name, spec)
        if key:
            headers["authorization"] = f"Bearer {key}"
        # Laid over rather than replacing, so an endpoint that wants its key
        # somewhere else can say so without also having to restate the parts
        # every endpoint shares.
        headers.update(spec.headers)
        self.client = httpx.AsyncClient(
            base_url=(spec.base_url or "").rstrip("/"),
            timeout=spec.timeout,
            headers=headers,
            params=spec.query or None,
        )
        # Asked once per model and remembered. A window does not change while
        # a process runs, and this must not become a round trip per turn.
        self._context: dict[str, int | None] = {}

    async def _remembered(self, model: str, ask) -> int | None:
        """Ask once and remember. For an answer that holds for the process.

        Ollama's does not, and asks every time instead -- see `context_for`
        there.
        """
        if model in self._context:
            return self._context[model]
        try:
            self._context[model] = await ask()
        except Exception:
            # Asking is an optimisation; a run must not die because the
            # endpoint was slow, gone, or answered something unexpected.
            self._context[model] = None
        return self._context[model]

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

    async def _stream_lines(self, path: str, payload: dict[str, Any]) -> AsyncIterator[str]:
        """The lines of a streamed reply, with the same refusals `_post` gives.

        The status is read before the first line, so an endpoint that refuses
        refuses whole rather than as an empty answer.
        """
        try:
            async with self.client.stream("POST", path, json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread())[:400].decode("utf-8", "replace")
                    raise ProviderError(
                        f"{self.name}: HTTP {response.status_code}: {body}",
                        provider=self.name,
                        retryable=response.status_code in _RETRYABLE_STATUS,
                    )
                async for line in response.aiter_lines():
                    yield line
        except httpx.RequestError as exc:
            raise ProviderError(
                f"{self.name}: cannot reach {self.spec.base_url}: {exc}",
                provider=self.name,
                retryable=True,
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
    supports_embeddings = True

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
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
        return payload

    async def stream(self, request: LLMRequest) -> AsyncIterator[Delta]:
        # A tool call arrives in fragments a reader would have to reassemble;
        # nothing here streams to a person while tools are on the table, so a
        # call that offers them is answered whole.
        if request.tools:
            async for delta in super().stream(request):
                yield delta
            return
        payload = self._payload(request)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        text: list[str] = []
        thinking: list[str] = []
        usage = Usage()
        stop: str | None = None
        model = request.model
        # `[DONE]` is the end; a `finish_reason` is one too, for a server that
        # never sends the marker. A stream that reaches neither has stopped
        # short, and what it carried so far is not the answer.
        finished = False
        async for line in self._stream_lines("/chat/completions", payload):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            body = line[len("data:") :].strip()
            if body == "[DONE]":
                finished = True
                break
            try:
                data = json.loads(body)
            except ValueError as exc:
                raise ProviderError(
                    f"{self.name}: stream chunk was not JSON: {body[:200]}", provider=self.name
                ) from exc
            if data.get("error"):
                raise ProviderError(f"{self.name}: {data['error']}", provider=self.name)
            model = data.get("model", model)
            if data.get("usage"):
                reported = data["usage"]
                details = reported.get("prompt_tokens_details") or {}
                usage = Usage(
                    input_tokens=reported.get("prompt_tokens", 0) or 0,
                    output_tokens=reported.get("completion_tokens", 0) or 0,
                    cache_read_tokens=details.get("cached_tokens", 0) or 0,
                    reasoning_tokens=(reported.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
                    cost=reported.get("cost"),
                )
            choices = data.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece_text = delta.get("content") or ""
            piece_thinking = delta.get("reasoning_content") or delta.get("reasoning") or ""
            if choices[0].get("finish_reason"):
                stop = choices[0]["finish_reason"]
                finished = True
            if piece_text:
                text.append(piece_text)
            if piece_thinking:
                thinking.append(piece_thinking)
            if piece_text or piece_thinking:
                yield Delta(text=piece_text, thinking=piece_thinking)
        if not finished:
            raise ProviderError(f"{self.name}: the stream ended before the answer was done", provider=self.name)
        whole = LLMResponse(
            text="".join(text),
            model=model,
            usage=usage,
            stop_reason=stop,
            meta={"thinking": "".join(thinking)} if thinking else {},
        )
        yield Delta(done=whole)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._payload(request)

        data = await self._post("/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.name}: response contained no choices", provider=self.name)
        message = choices[0].get("message") or {}
        tool_calls = []
        for call in message.get("tool_calls") or []:
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
        # How much of the prompt the endpoint already had. An agent loop resends
        # its whole conversation every turn, so this is the difference between a
        # cheap long run and an expensive one -- and it was being reported as
        # zero on every run through here, which read as a measurement and was
        # not one. Endpoints that cache nothing omit the key; absent is zero.
        details = usage.get("prompt_tokens_details") or {}
        return LLMResponse(
            text=message.get("content") or "",
            model=data.get("model", request.model),
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0) or 0,
                output_tokens=usage.get("completion_tokens", 0) or 0,
                cache_read_tokens=details.get("cached_tokens", 0) or 0,
                cache_write_tokens=details.get("cache_write_tokens", 0) or 0,
                reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
                # Absent means the endpoint did not say, which is a different
                # fact from having charged nothing.
                cost=usage.get("cost"),
            ),
            stop_reason=choices[0].get("finish_reason"),
            tool_calls=tool_calls,
        )

    async def health(self) -> tuple[bool, str]:
        return await self._list_health("/models", key="data", field="id")

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = await self._post("/embeddings", {"model": model, "input": texts})
        rows = data.get("data") or []
        try:
            ordered = sorted(rows, key=lambda row: int(row["index"]))
            if [int(row["index"]) for row in ordered] != list(range(len(texts))):
                raise ValueError("embedding indices do not match the inputs")
            vectors = [[float(value) for value in row["embedding"]] for row in ordered]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                f"{self.name}: embedding response had an invalid shape",
                provider=self.name,
            ) from exc
        _check_embeddings(self.name, vectors, len(texts))
        return vectors

    async def context_for(self, model: str) -> int | None:
        """`/models` lists every model with its `context_length`."""

        async def ask() -> int | None:
            response = await self.client.get("/models")
            if response.status_code >= 400:
                return None
            for entry in response.json().get("data") or []:
                if entry.get("id") != model:
                    continue
                # Two numbers, and the smaller one is the true one. The top
                # level is what the model can do; `top_provider` is what the
                # endpoint serving it will allow, and forty of OpenRouter's
                # models disagree with themselves here -- z-ai/glm-5.3-flash
                # says 1,310,720 and 1,048,576. Believing the larger means
                # filling a window past where it will be refused.
                served = (entry.get("top_provider") or {}).get("context_length")
                if isinstance(served, int):
                    return served
                return int(entry["context_length"])
            return None

        return await self._remembered(model, ask)


class OllamaProvider(_HttpProvider):
    """Ollama's native /api/chat endpoint."""

    type = "ollama"
    supports_embeddings = True

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
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
        return payload

    async def stream(self, request: LLMRequest) -> AsyncIterator[Delta]:
        # See the OpenAI-shaped provider: tools are answered whole.
        if request.tools:
            async for delta in super().stream(request):
                yield delta
            return
        payload = self._payload(request)
        payload["stream"] = True
        text: list[str] = []
        thinking: list[str] = []
        model = request.model
        async for line in self._stream_lines("/api/chat", payload):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except ValueError as exc:
                raise ProviderError(f"{self.name}: stream line was not JSON: {line[:200]}", provider=self.name) from exc
            if data.get("error"):
                raise ProviderError(f"{self.name}: {data['error']}", provider=self.name)
            model = data.get("model", model)
            message = data.get("message") or {}
            piece_text = message.get("content") or ""
            piece_thinking = message.get("thinking") or ""
            if piece_text:
                text.append(piece_text)
            if piece_thinking:
                thinking.append(piece_thinking)
            if data.get("done"):
                whole = LLMResponse(
                    text="".join(text),
                    model=model,
                    usage=Usage(
                        input_tokens=data.get("prompt_eval_count", 0) or 0,
                        output_tokens=data.get("eval_count", 0) or 0,
                    ),
                    stop_reason=data.get("done_reason"),
                    meta={"thinking": "".join(thinking)} if thinking else {},
                )
                yield Delta(text=piece_text, thinking=piece_thinking, done=whole)
                return
            if piece_text or piece_thinking:
                yield Delta(text=piece_text, thinking=piece_thinking)
        raise ProviderError(f"{self.name}: the stream ended before the answer was done", provider=self.name)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._payload(request)

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

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = await self._post("/api/embed", {"model": model, "input": texts})
        try:
            vectors = [[float(value) for value in row] for row in (data.get("embeddings") or [])]
        except (TypeError, ValueError) as exc:
            raise ProviderError(
                f"{self.name}: embedding response had an invalid shape",
                provider=self.name,
            ) from exc
        _check_embeddings(self.name, vectors, len(texts))
        return vectors

    async def context_for(self, model: str) -> int | None:
        """What Ollama **loaded**, which is not what the model can do.

        `/api/show` reports the model's own capability -- 262,144 for a
        qwen3.5 -- and the server then loads it with whatever `num_ctx` it was
        told, measured on this machine at **4,096**. Sixty-four times smaller,
        and nothing announces the difference: an endpoint asked to hold more
        than it loaded just drops the rest. So the answer comes from
        `/api/ps`, which says what is actually running.

        A model that is not loaded has no answer yet, and the silence is not
        remembered -- the first call to that model is what loads it, so the
        next node can ask again and get a number.
        """

        async def ask() -> int | None:
            response = await self.client.get("/api/ps")
            if response.status_code >= 400:
                return None
            for entry in response.json().get("models") or []:
                if entry.get("name") == model:
                    size = entry.get("context_length")
                    return size if isinstance(size, int) else None
            return None

        # Not remembered at all, unlike the OpenAI-shaped one. That answer is
        # a property of a deployment and holds for the process; this one is
        # "what is loaded right now", and a single request from any client --
        # poieo or the editor someone has open beside it -- reloads the model
        # at a different size. Measured: `num_ctx=16384` took 5.43s to reload,
        # and the next plain request took 3.91s to put 4096 back. A localhost
        # GET once per node execution is cheaper than being wrong about that.
        return await ask()
