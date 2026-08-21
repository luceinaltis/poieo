import httpx
import pytest

from poieo.binding import ProviderSpec, ResolvedModel
from poieo.errors import ProviderError
from poieo.providers import LLMRequest, LLMResponse, build_provider
from poieo.providers.anthropic_provider import AnthropicProvider
from poieo.providers.base import ToolCall, ToolDef
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


def _message(**overrides):
    from types import SimpleNamespace

    base = dict(
        id="msg_1",
        model="claude-opus-5",
        stop_reason="end_turn",
        stop_details=None,
        content=[
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="text", text="hello "),
            SimpleNamespace(type="text", text="world"),
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
