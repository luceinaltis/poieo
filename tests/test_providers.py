import httpx
import pytest

from poieo.binding import ProviderSpec, ResolvedModel
from poieo.errors import ProviderError
from poieo.providers import LLMRequest, LLMResponse, build_provider
from poieo.providers.anthropic_provider import AnthropicProvider
from poieo.providers.base import ToolCall, ToolDef
from poieo.providers.local import OllamaProvider, OpenAICompatibleProvider
from poieo.providers.mock import MockProvider


@pytest.fixture
def anthropic_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    return AnthropicProvider("claude", ProviderSpec(type="anthropic"))


def build(provider, model, **params):
    return provider._build_kwargs(
        LLMRequest(model=model, messages=[{"role": "user", "content": "hi"}], params=params)
    )


def test_adaptive_thinking_and_effort_on_a_current_model(anthropic_provider):
    kwargs = build(anthropic_provider, "claude-opus-5", effort="xhigh", max_tokens=100)
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "xhigh"}
    assert kwargs["max_tokens"] == 100


def test_thinking_can_be_summarized_or_disabled(anthropic_provider):
    assert build(anthropic_provider, "claude-opus-5", thinking="summarized")["thinking"] == {
        "type": "adaptive",
        "display": "summarized",
    }
    assert build(anthropic_provider, "claude-opus-5", thinking="off")["thinking"] == {
        "type": "disabled"
    }


def test_disabled_thinking_at_high_effort_is_refused_before_the_request(anthropic_provider):
    # The API returns 400 for this pairing; catching it locally saves a round trip.
    with pytest.raises(ProviderError, match="cannot be disabled at effort"):
        build(anthropic_provider, "claude-opus-5", thinking="off", effort="max")


def test_older_models_get_no_thinking_or_effort(anthropic_provider):
    kwargs = build(anthropic_provider, "claude-haiku-4-5", effort="high", thinking="auto")
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs
    assert any("does not support effort" in w for w in anthropic_provider.warnings)


def test_sampling_is_dropped_where_the_api_rejects_it(anthropic_provider):
    kwargs = build(anthropic_provider, "claude-opus-5", temperature=0.7)
    assert "temperature" not in kwargs
    assert any("rejects temperature" in w for w in anthropic_provider.warnings)


def test_sampling_is_kept_where_it_is_supported(anthropic_provider):
    assert build(anthropic_provider, "claude-haiku-4-5", temperature=0.7)["temperature"] == 0.7


def test_unknown_params_pass_straight_through(anthropic_provider):
    # A new API parameter should be usable from a binding without a code change.
    assert build(anthropic_provider, "claude-opus-5", inference_geo="us")["inference_geo"] == "us"


def test_system_prompt_is_forwarded(anthropic_provider):
    kwargs = anthropic_provider._build_kwargs(
        LLMRequest(model="claude-opus-5", messages=[], system="be terse", params={})
    )
    assert kwargs["system"] == "be terse"


def _mock_client(provider, handler):
    provider.client = httpx.AsyncClient(
        base_url=str(provider.client.base_url), transport=httpx.MockTransport(handler)
    )
    return provider


async def test_openai_compatible_provider_maps_the_response():
    provider = build_provider(
        "vllm", ProviderSpec(type="openai_compatible", base_url="http://x/v1")
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "model": "qwen",
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    _mock_client(provider, handler)
    response = await provider.complete(
        LLMRequest(
            model="qwen",
            messages=[{"role": "user", "content": "hi"}],
            system="be terse",
            params={"max_tokens": 64},
        )
    )
    await provider.aclose()

    assert seen["path"] == "/v1/chat/completions"
    assert '"system"' in seen["body"]  # system is folded into the message list
    assert response.text == "hello"
    assert response.usage.output_tokens == 2


async def test_ollama_provider_moves_params_into_options():
    provider = build_provider(
        "ollama", ProviderSpec(type="ollama", base_url="http://x")
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.read()))
        return httpx.Response(
            200,
            json={"model": "llama", "message": {"content": "hey"}, "eval_count": 3},
        )

    _mock_client(provider, handler)
    response = await provider.complete(
        LLMRequest(
            model="llama",
            messages=[{"role": "user", "content": "hi"}],
            params={"max_tokens": 32, "temperature": 0.1},
        )
    )
    await provider.aclose()

    assert seen["options"] == {"num_predict": 32, "temperature": 0.1}
    assert response.text == "hey"


async def test_http_errors_are_marked_retryable_only_when_they_are():
    provider = build_provider("ollama", ProviderSpec(type="ollama", base_url="http://x"))
    _mock_client(provider, lambda request: httpx.Response(503, text="busy"))
    with pytest.raises(ProviderError) as exc:
        await provider.complete(LLMRequest(model="m", messages=[]))
    assert exc.value.retryable

    _mock_client(provider, lambda request: httpx.Response(400, text="bad model"))
    with pytest.raises(ProviderError) as exc:
        await provider.complete(LLMRequest(model="m", messages=[]))
    assert not exc.value.retryable
    await provider.aclose()


def test_missing_api_key_env_is_reported_at_construction():
    with pytest.raises(ProviderError, match=r"\$NOPE_KEY is not set"):
        build_provider(
            "vllm",
            ProviderSpec(
                type="openai_compatible", base_url="http://x/v1", api_key_env="NOPE_KEY"
            ),
        )


def test_credential_for_reads_the_environment_without_opening_anything(monkeypatch):
    """The rule in one place, so it can be checked before anything is armed.
    A provider that names no variable resolves its own credential and is not
    this function's business."""
    from poieo.providers import credential_for

    spec = ProviderSpec(type="openai_compatible", base_url="http://x/v1")
    assert credential_for("vllm", spec) is None

    keyed = ProviderSpec(
        type="openai_compatible", base_url="http://x/v1", api_key_env="POIEO_TEST_KEY"
    )
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-whatever")
    assert credential_for("vllm", keyed) == "sk-whatever"

    monkeypatch.delenv("POIEO_TEST_KEY")
    with pytest.raises(ProviderError, match=r"\$POIEO_TEST_KEY is not set"):
        credential_for("vllm", keyed)


def test_unknown_provider_type_is_rejected():
    with pytest.raises(Exception):
        ProviderSpec(type="telepathy")


def test_resolved_model_describes_the_binding():
    resolved = ResolvedModel(
        role="writer",
        provider_name="claude",
        provider=ProviderSpec(type="anthropic"),
        model="claude-opus-5",
    )
    assert resolved.describe() == "writer -> claude:claude-opus-5"


class _FakeStream:
    """Stands in for `client.messages.stream(...)`'s async context manager."""

    def __init__(self, message):
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self._message


def _block(**kwargs):
    """A fake pydantic-ish content block: attributes plus a model_dump()."""
    from types import SimpleNamespace

    block = SimpleNamespace(**kwargs)
    block.model_dump = lambda: dict(kwargs)
    return block


def _message(**overrides):
    from types import SimpleNamespace

    base = dict(
        id="msg_1",
        model="claude-opus-5",
        stop_reason="end_turn",
        stop_details=None,
        content=[
            _block(type="thinking", thinking="..."),
            _block(type="text", text="hello "),
            _block(type="text", text="world"),
        ],
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=4,
            cache_read_input_tokens=6,
            cache_creation_input_tokens=0,
        ),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


async def test_completion_joins_text_blocks_and_reports_usage(anthropic_provider, monkeypatch):
    monkeypatch.setattr(
        anthropic_provider.client.messages, "stream", lambda **kw: _FakeStream(_message())
    )
    response = await anthropic_provider.complete(
        LLMRequest(model="claude-opus-5", messages=[{"role": "user", "content": "hi"}])
    )
    assert response.text == "hello world"  # thinking blocks are not part of the output
    assert response.usage.input_tokens == 10
    assert response.usage.cache_read_tokens == 6


async def test_completion_stashes_raw_content_including_thinking_blocks(
    anthropic_provider, monkeypatch
):
    thinking = _block(type="thinking", thinking="let me see...", signature="sig-abc")
    text = _block(type="text", text="checking")
    tool_use = _block(type="tool_use", id="c1", name="read_file", input={"path": "a"})
    message = _message(content=[thinking, text, tool_use], stop_reason="tool_use")

    monkeypatch.setattr(
        anthropic_provider.client.messages, "stream", lambda **kw: _FakeStream(message)
    )
    response = await anthropic_provider.complete(
        LLMRequest(model="claude-opus-5", messages=[{"role": "user", "content": "hi"}])
    )

    assert response.meta["raw_content"] == [
        {"type": "thinking", "thinking": "let me see...", "signature": "sig-abc"},
        {"type": "text", "text": "checking"},
        {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a"}},
    ]
    assert response.tool_calls == [ToolCall(id="c1", name="read_file", arguments={"path": "a"})]


async def test_a_refusal_becomes_a_provider_error(anthropic_provider, monkeypatch):
    from types import SimpleNamespace

    refused = _message(
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber", explanation="no"),
        content=[],
    )
    monkeypatch.setattr(
        anthropic_provider.client.messages, "stream", lambda **kw: _FakeStream(refused)
    )
    with pytest.raises(ProviderError, match="declined the request"):
        await anthropic_provider.complete(LLMRequest(model="claude-opus-5", messages=[]))


def test_llm_request_and_response_default_to_no_tools():
    request = LLMRequest(model="m", messages=[])
    response = LLMResponse(text="t", model="m")
    assert request.tools == []
    assert response.tool_calls == []


async def test_mock_scripts_tool_calls():
    spec = ProviderSpec.model_validate(
        {
            "type": "mock",
            "options": {
                "responses": {
                    "worker": [
                        {"tool_calls": [{"name": "read_file", "arguments": {"path": "a.txt"}}]},
                        "done",
                    ]
                }
            },
        }
    )
    provider = MockProvider("fake", spec)
    request = LLMRequest(model="m", messages=[], role="worker")

    first = await provider.complete(request)
    assert first.text == ""
    assert first.tool_calls == [ToolCall(id="mock_1", name="read_file", arguments={"path": "a.txt"})]
    assert first.stop_reason == "tool_use"

    second = await provider.complete(request)
    assert second.text == "done"
    assert second.tool_calls == []


from poieo.providers.local import _ollama_messages, _openai_messages, _wire_tools

NEUTRAL_HISTORY = [
    {"role": "user", "content": "go"},
    {
        "role": "assistant",
        "content": "checking",
        "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}],
    },
    {"role": "tool", "tool_call_id": "c1", "content": "data"},
]

A_TOOL = ToolDef(name="read_file", description="read", input_schema={"type": "object"})


def test_wire_tools_wraps_openai_style():
    assert _wire_tools([A_TOOL]) == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "read",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_openai_messages_translation():
    request = LLMRequest(model="m", messages=NEUTRAL_HISTORY, system="sys")
    messages = _openai_messages(request)
    assert messages[0] == {"role": "system", "content": "sys"}
    assistant = messages[2]
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
    import json
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "a"}
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": "data"}


def test_ollama_messages_translation():
    request = LLMRequest(model="m", messages=NEUTRAL_HISTORY, system=None)
    messages = _ollama_messages(request)
    assistant = messages[1]
    # Ollama takes arguments as a dict, not a JSON string.
    assert assistant["tool_calls"][0]["function"]["arguments"] == {"path": "a"}
    assert messages[2]["role"] == "tool"


async def test_openai_complete_parses_tool_calls(monkeypatch):
    spec = ProviderSpec.model_validate(
        {"type": "openai_compatible", "base_url": "http://x"}
    )
    provider = OpenAICompatibleProvider("vllm", spec)

    async def fake_post(path, payload):
        assert payload["tools"][0]["function"]["name"] == "read_file"
        return {
            "model": "m",
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "c9",
                        "function": {"name": "read_file", "arguments": '{"path": "a"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    response = await provider.complete(
        LLMRequest(model="m", messages=[{"role": "user", "content": "go"}], tools=[A_TOOL])
    )
    assert response.tool_calls == [ToolCall(id="c9", name="read_file", arguments={"path": "a"})]
    await provider.aclose()


async def test_openai_complete_rejects_malformed_tool_arguments(monkeypatch):
    spec = ProviderSpec.model_validate(
        {"type": "openai_compatible", "base_url": "http://x"}
    )
    provider = OpenAICompatibleProvider("vllm", spec)

    async def fake_post(path, payload):
        return {
            "model": "m",
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{"function": {"name": "read_file", "arguments": "{not json"}}],
                },
            }],
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    with pytest.raises(ProviderError, match="malformed"):
        await provider.complete(
            LLMRequest(model="m", messages=[{"role": "user", "content": "go"}], tools=[A_TOOL])
        )
    await provider.aclose()


async def test_ollama_complete_parses_tool_calls(monkeypatch):
    spec = ProviderSpec.model_validate({"type": "ollama", "base_url": "http://x"})
    provider = OllamaProvider("ollama", spec)

    async def fake_post(path, payload):
        assert payload["tools"][0]["function"]["name"] == "read_file"
        return {
            "model": "m",
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "a"}}}],
            },
            "done_reason": "stop",
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    response = await provider.complete(
        LLMRequest(model="m", messages=[{"role": "user", "content": "go"}], tools=[A_TOOL])
    )
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "read_file"
    assert response.tool_calls[0].arguments == {"path": "a"}
    assert response.tool_calls[0].id.startswith("call_")
    await provider.aclose()


from poieo.providers.anthropic_provider import _anthropic_messages, _anthropic_tools


def test_anthropic_tools_shape():
    assert _anthropic_tools([A_TOOL]) == [
        {"name": "read_file", "description": "read", "input_schema": {"type": "object"}}
    ]


def test_anthropic_messages_translation_merges_tool_results():
    history = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [
                {"id": "c1", "name": "read_file", "arguments": {"path": "a"}},
                {"id": "c2", "name": "list_dir", "arguments": {}},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "data-1"},
        {"role": "tool", "tool_call_id": "c2", "content": "data-2"},
    ]
    messages = _anthropic_messages(history)
    assert messages[0] == {"role": "user", "content": "go"}
    assistant = messages[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "text", "text": "checking"}
    assert assistant["content"][1] == {
        "type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a"}
    }
    # Both tool results land in ONE user turn.
    results = messages[2]
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["c1", "c2"]
    assert results["content"][0]["type"] == "tool_result"
    assert len(messages) == 3


def test_anthropic_messages_replays_raw_content_verbatim():
    # A thinking block has no ``content``/``tool_calls`` equivalent in the
    # neutral history -- it only survives if raw_content is replayed as-is
    # instead of being reconstructed from text/tool_calls.
    raw_blocks = [
        {"type": "thinking", "thinking": "let me see...", "signature": "sig-abc"},
        {"type": "text", "text": "checking"},
        {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a"}},
    ]
    history = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}],
            "raw_content": raw_blocks,
        },
        {"role": "tool", "tool_call_id": "c1", "content": "data-1"},
    ]
    messages = _anthropic_messages(history)
    assistant = messages[1]
    assert assistant == {"role": "assistant", "content": raw_blocks}
    # It must be the exact list, untouched -- no reconstruction happened.
    assert assistant["content"] is raw_blocks


async def test_ollama_captures_separated_thinking(monkeypatch):
    spec = ProviderSpec.model_validate({"type": "ollama", "base_url": "http://x"})
    provider = OllamaProvider("ollama", spec)

    async def fake_post(path, payload):
        return {
            "model": "m",
            "message": {"content": "answer", "thinking": "hmm, tricky"},
            "done_reason": "stop",
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    response = await provider.complete(
        LLMRequest(model="m", messages=[{"role": "user", "content": "q"}])
    )
    assert response.meta["thinking"] == "hmm, tricky"
    await provider.aclose()


async def test_anthropic_captures_thinking_blocks(monkeypatch, anthropic_provider):
    message = _message(
        content=[
            _block(type="thinking", thinking="step one, step two"),
            _block(type="text", text="final answer"),
        ]
    )
    monkeypatch.setattr(
        anthropic_provider.client.messages, "stream", lambda **kw: _FakeStream(message)
    )
    response = await anthropic_provider.complete(
        LLMRequest(model="claude-opus-5", messages=[{"role": "user", "content": "q"}])
    )
    assert response.meta["thinking"] == "step one, step two"
    assert response.text == "final answer"


async def test_mock_latency_makes_a_call_take_time():
    """A mock that answers instantly makes every live view look idle."""
    import time

    from poieo.binding import ProviderSpec
    from poieo.providers.base import LLMRequest
    from poieo.providers.mock import MockProvider

    spec = ProviderSpec.model_validate(
        {"type": "mock", "options": {"responses": {"*": "hi"}, "latency": 0.05}}
    )
    provider = MockProvider("slow", spec)

    started = time.monotonic()
    response = await provider.complete(LLMRequest(model="m", messages=[]))
    elapsed = time.monotonic() - started

    assert response.text == "hi"
    assert elapsed >= 0.04


async def test_mock_has_no_latency_by_default():
    import time

    from poieo.binding import ProviderSpec
    from poieo.providers.base import LLMRequest
    from poieo.providers.mock import MockProvider

    spec = ProviderSpec.model_validate({"type": "mock", "options": {"responses": {"*": "hi"}}})
    provider = MockProvider("quick", spec)

    started = time.monotonic()
    await provider.complete(LLMRequest(model="m", messages=[]))

    assert time.monotonic() - started < 0.02
