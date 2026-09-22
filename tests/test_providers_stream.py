"""An answer as it is written: the local backends stream, every other backend
answers whole, and both come through one seam.

Design: docs/binding.md
"""

import json

import httpx
import pytest
from test_providers import _mock_client

from poieo.binding import ProviderSpec
from poieo.errors import ProviderError
from poieo.providers import Delta, LLMRequest, build_provider


def _request(**params):
    return LLMRequest(model="m", messages=[{"role": "user", "content": "hi"}], params=params, role="default")


async def _collect(provider, request):
    deltas = []
    async for delta in provider.stream(request):
        deltas.append(delta)
    return deltas


async def test_ollama_streams_thinking_then_words_and_ends_with_the_whole_answer():
    provider = build_provider("local", ProviderSpec(type="ollama", base_url="http://x"))
    lines = [
        {"model": "qwen", "message": {"role": "assistant", "content": "", "thinking": "Let me "}, "done": False},
        {"model": "qwen", "message": {"role": "assistant", "content": "", "thinking": "see."}, "done": False},
        {"model": "qwen", "message": {"role": "assistant", "content": "Four"}, "done": False},
        {"model": "qwen", "message": {"role": "assistant", "content": "."}, "done": False},
        {
            "model": "qwen",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 12,
            "eval_count": 9,
        },
    ]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, content="\n".join(json.dumps(line) for line in lines).encode())

    deltas = await _collect(_mock_client(provider, handler), _request(max_tokens=50))

    assert seen["body"]["stream"] is True
    assert seen["body"]["options"] == {"num_predict": 50}
    assert [(d.thinking, d.text) for d in deltas] == [("Let me ", ""), ("see.", ""), ("", "Four"), ("", "."), ("", "")]
    assert [d.done is not None for d in deltas] == [False, False, False, False, True]
    whole = deltas[-1].done
    assert whole.text == "Four."
    assert whole.meta["thinking"] == "Let me see."
    assert whole.stop_reason == "stop"
    assert (whole.usage.input_tokens, whole.usage.output_tokens) == (12, 9)
    assert whole.model == "qwen"


async def test_openai_compatible_streams_server_sent_deltas_and_reads_the_final_usage():
    provider = build_provider("vllm", ProviderSpec(type="openai_compatible", base_url="http://x/v1"))
    chunks = [
        {"model": "q", "choices": [{"delta": {"role": "assistant", "reasoning_content": "hm"}, "finish_reason": None}]},
        {"model": "q", "choices": [{"delta": {"content": "Fo"}, "finish_reason": None}]},
        {"model": "q", "choices": [{"delta": {"content": "ur."}, "finish_reason": "length"}]},
        {"model": "q", "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
    ]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        wire = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, content=wire.encode(), headers={"content-type": "text/event-stream"})

    deltas = await _collect(_mock_client(provider, handler), _request())

    assert seen["body"]["stream"] is True
    assert seen["body"]["stream_options"] == {"include_usage": True}
    assert [(d.thinking, d.text) for d in deltas if d.done is None] == [("hm", ""), ("", "Fo"), ("", "ur.")]
    whole = deltas[-1].done
    assert whole is not None
    assert whole.text == "Four."
    assert whole.meta["thinking"] == "hm"
    assert whole.stop_reason == "length"
    assert (whole.usage.input_tokens, whole.usage.output_tokens) == (7, 3)


async def test_a_backend_without_a_stream_answers_whole_through_the_same_seam():
    provider = build_provider("fake", ProviderSpec(type="mock", options={"responses": {"default": "Whole answer."}}))

    deltas = await _collect(provider, _request())

    assert len(deltas) == 1
    assert deltas[0] == Delta(text="Whole answer.", thinking="", done=deltas[0].done)
    assert deltas[0].done.text == "Whole answer."


async def test_a_stream_the_endpoint_refuses_is_a_provider_error_not_a_half_answer():
    provider = build_provider("local", ProviderSpec(type="ollama", base_url="http://x"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"loading")

    with pytest.raises(ProviderError) as refused:
        await _collect(_mock_client(provider, handler), _request())
    assert "503" in str(refused.value)
    assert refused.value.retryable


async def test_a_stream_that_ends_before_it_is_done_is_a_provider_error():
    provider = build_provider("local", ProviderSpec(type="ollama", base_url="http://x"))

    def handler(request: httpx.Request) -> httpx.Response:
        line = json.dumps({"message": {"role": "assistant", "content": "Fo"}, "done": False})
        return httpx.Response(200, content=line.encode())

    with pytest.raises(ProviderError) as cut:
        await _collect(_mock_client(provider, handler), _request())
    assert "before the answer was done" in str(cut.value)


async def test_a_call_that_offers_tools_is_answered_whole_because_a_stream_would_break_them_up():
    provider = build_provider("local", ProviderSpec(type="ollama", base_url="http://x"))
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "model": "qwen",
                "message": {"role": "assistant", "content": "done"},
                "done": True,
                "done_reason": "stop",
            },
        )

    from poieo.providers.base import ToolDef

    request = LLMRequest(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[ToolDef(name="read_file", description="read", input_schema={"type": "object"})],
    )
    deltas = await _collect(_mock_client(provider, handler), request)

    assert seen["body"]["stream"] is False
    assert len(deltas) == 1 and deltas[0].done.text == "done"


async def test_an_openai_stream_that_ends_without_its_end_marker_is_a_provider_error():
    provider = build_provider("vllm", ProviderSpec(type="openai_compatible", base_url="http://x/v1"))

    def handler(request: httpx.Request) -> httpx.Response:
        chunk = {"choices": [{"delta": {"content": "Fo"}, "finish_reason": None}]}
        return httpx.Response(200, content=f"data: {json.dumps(chunk)}\n\n".encode())

    with pytest.raises(ProviderError) as cut:
        await _collect(_mock_client(provider, handler), _request())
    assert "before the answer was done" in str(cut.value)


async def test_an_openai_stream_may_end_with_a_finish_reason_and_no_marker():
    provider = build_provider("vllm", ProviderSpec(type="openai_compatible", base_url="http://x/v1"))

    def handler(request: httpx.Request) -> httpx.Response:
        chunk = {"choices": [{"delta": {"content": "Four."}, "finish_reason": "stop"}]}
        return httpx.Response(200, content=f"data: {json.dumps(chunk)}\n\n".encode())

    deltas = await _collect(_mock_client(provider, handler), _request())
    assert deltas[-1].done is not None and deltas[-1].done.text == "Four."
