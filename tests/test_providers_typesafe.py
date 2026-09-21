"""A backend that decides instead of writing.

TypeSafe's Jev takes a state and typed questions and answers each with a
choice, a yes/no probability or a score. These tests pin the one contract that
lets it sit behind an ordinary agent node: the rendered prompt is the state,
`params.questions` says what to decide, and the answers come back as JSON that
`output: {format: json}` and a router can read.
"""

from __future__ import annotations

import json

import httpx
import pytest

from poieo.binding import BindingSpec, ProviderSpec
from poieo.errors import ProviderError
from poieo.graph import GraphSpec
from poieo.providers import LLMRequest, ProviderPool, build_provider, check_credentials
from poieo.providers.base import Hands, ToolDef
from poieo.runtime.executor import execute
from poieo.store import NullStore

QUESTIONS = {
    "verdict": {
        "type": "choice",
        "instructions": "Is this proposal ready to build?",
        "criteria": {"NARROW": "too big for one change", "DROP": "not wanted", "BUILD": "ready"},
    }
}

ANSWERS = {
    "verdict": {
        "type": "choice",
        "choice": "NARROW",
        "probabilities": {"NARROW": 0.8, "DROP": 0.05, "BUILD": 0.15},
        "confidence": 0.8,
    }
}


def _decided(seen: dict | None = None, status: int = 200, body: dict | list | None = None):
    """A handler that answers like the API and remembers what it was asked."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen["url"] = str(request.url)
            seen["path"] = request.url.path
            seen["headers"] = dict(request.headers)
            seen["body"] = json.loads(request.read().decode())
        if status != 200:
            return httpx.Response(status, json=body or {"error": "no"})
        return httpx.Response(
            200,
            json=body or {"model": "jev-1.13.0", "answers": ANSWERS, "usage": {"input_tokens": 41, "output_tokens": 3}},
        )

    return handler


def _mock_client(provider, handler):
    provider.client = httpx.AsyncClient(
        base_url=str(provider.client.base_url),
        headers=provider.client.headers,
        params=provider.client.params,
        transport=httpx.MockTransport(handler),
    )


@pytest.fixture
def jev(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-not-a-real-key")
    provider = build_provider("jev", ProviderSpec(type="typesafe"))
    yield provider


def _ask(**overrides) -> LLMRequest:
    request = LLMRequest(
        model="jev-latest",
        messages=[{"role": "user", "content": "Proposal: add dark mode"}],
        system="You judge proposals.",
        params={"questions": QUESTIONS, "max_tokens": 600, "temperature": 0},
    )
    for key, value in overrides.items():
        setattr(request, key, value)
    return request


async def test_the_endpoint_needs_only_its_name(jev):
    """The address and the key variable are the parts a person gets wrong,
    and they are the parts poieo can know. Checked on the wire, as sent."""
    seen: dict = {}
    _mock_client(jev, _decided(seen))
    await jev.complete(_ask())
    await jev.aclose()

    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["headers"]["authorization"] == "Bearer ts-test-not-a-real-key"


@pytest.mark.parametrize(
    ("spec", "variable"),
    [
        ({"type": "typesafe"}, "TYPESAFE_API_KEY"),
        # The same gap for a preset: the daemon armed a task whose key it had
        # never checked, because the binding never spelled the variable out.
        ({"type": "groq"}, "GROQ_API_KEY"),
    ],
)
def test_a_key_the_binding_left_out_is_still_checked_before_anything_is_armed(monkeypatch, spec, variable):
    monkeypatch.delenv(variable, raising=False)
    binding = BindingSpec.model_validate(
        {"name": "b", "providers": {"hosted": spec}, "default": {"provider": "hosted", "model": "m"}}
    )
    with pytest.raises(ProviderError, match=rf"\${variable} is not set"):
        check_credentials(binding, {"judge"})


async def test_the_prompt_is_the_state_and_the_questions_come_from_params(jev):
    seen: dict = {}
    _mock_client(jev, _decided(seen))

    await jev.complete(_ask())
    await jev.aclose()

    assert seen["path"] == "/v1/systemone"
    assert seen["body"]["model"] == "jev-latest"
    # The system block is part of what the model is shown, so it is part of
    # the state; a card always writes one.
    assert seen["body"]["state"] == "You judge proposals.\n\nProposal: add dark mode"
    assert seen["body"]["questions"] == QUESTIONS
    # Generation settings inherited from the binding's `default` describe
    # writing, and this model writes nothing. The API documents exactly three
    # request fields, so nothing else is sent -- and nothing is silently
    # forgotten either; the run record test below checks that half.
    assert set(seen["body"]) == {"model", "state", "questions"}


async def test_structured_content_is_written_into_the_state_as_json(jev):
    seen: dict = {}
    _mock_client(jev, _decided(seen))
    blocks = [{"type": "text", "text": "Proposal: add dark mode"}]
    await jev.complete(_ask(messages=[{"role": "user", "content": blocks}], system=None))
    await jev.aclose()
    assert seen["body"]["state"] == json.dumps(blocks, ensure_ascii=False)


async def test_nothing_to_decide_on_is_refused_before_any_request(jev):
    calls: list[str] = []
    _mock_client(jev, lambda request: calls.append(request.url.path) or httpx.Response(500))
    with pytest.raises(ProviderError, match="nothing to decide on") as exc:
        await jev.complete(_ask(messages=[{"role": "user", "content": ""}], system=None))
    await jev.aclose()
    assert not exc.value.retryable
    assert calls == []


async def test_answers_come_back_as_json_a_router_can_read(jev):
    _mock_client(jev, _decided())

    response = await jev.complete(_ask())
    await jev.aclose()

    assert json.loads(response.text) == ANSWERS
    assert response.model == "jev-1.13.0"
    assert response.usage.input_tokens == 41
    assert response.usage.output_tokens == 3
    # The endpoint does not say what it charged; None is not zero.
    assert response.usage.cost is None
    assert response.tool_calls == []
    assert response.meta["ignored_params"] == ["max_tokens", "temperature"]


async def test_a_node_with_tools_is_refused_before_any_request(jev):
    calls: list[str] = []
    _mock_client(jev, lambda request: calls.append(request.url.path) or httpx.Response(500))

    tool = ToolDef(name="read_file", description="", input_schema={"type": "object"})
    with pytest.raises(ProviderError, match="tools") as exc:
        await jev.complete(_ask(tools=[tool]))
    assert not exc.value.retryable

    # A node that hands over the means to run tools is refused the same way,
    # even before it has named one.
    async def never(call):
        return "", True

    with pytest.raises(ProviderError, match="tools"):
        await jev.complete(_ask(hands=Hands(run=never)))
    await jev.aclose()

    assert calls == []


async def test_a_node_that_says_nothing_to_decide_is_refused(jev):
    _mock_client(jev, _decided())
    for params in ({}, {"questions": {}}, {"questions": "is it good?"}):
        with pytest.raises(ProviderError, match="questions") as exc:
            await jev.complete(_ask(params=params))
        assert not exc.value.retryable
    await jev.aclose()


async def test_a_conversation_is_refused(jev):
    """One state, one set of answers. A history means a tool loop or a chat,
    and this model holds neither."""
    _mock_client(jev, _decided())
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
    with pytest.raises(ProviderError, match="conversation"):
        await jev.complete(_ask(messages=history))
    await jev.aclose()


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(401, False), (422, False), (429, True), (529, True)],
)
async def test_http_errors_are_retried_only_when_the_server_is_the_problem(jev, status, retryable):
    _mock_client(jev, _decided(status=status, body={"error": {"message": "criteria must be a map"}}))
    with pytest.raises(ProviderError, match=f"HTTP {status}") as exc:
        await jev.complete(_ask())
    await jev.aclose()
    assert exc.value.retryable is retryable
    # The body is the only place the API explains a 422, so it travels.
    assert "criteria must be a map" in str(exc.value)


@pytest.mark.parametrize("body", [{"model": "jev-1.13.0", "usage": {}}, ["not", "an", "object"]])
async def test_a_response_without_answers_is_a_failure(jev, body):
    """A provider failure, in the provider's voice -- never a stray
    AttributeError out of a 200 that was not the API's shape."""
    _mock_client(jev, _decided(body=body))
    with pytest.raises(ProviderError, match="answers"):
        await jev.complete(_ask())
    await jev.aclose()


async def test_the_probe_asks_one_cheap_question_and_never_raises(jev):
    seen: dict = {}
    _mock_client(jev, _decided(seen))
    assert await jev.health() == (True, "reachable (jev-1.13.0)")
    assert seen["path"] == "/v1/systemone"
    assert len(seen["body"]["questions"]) == 1

    _mock_client(jev, _decided(status=401))
    healthy, detail = await jev.health()
    assert not healthy
    assert detail.startswith("HTTP 401")

    _mock_client(jev, _decided(body=["a", "proxy", "answered"]))
    healthy, detail = await jev.health()
    assert not healthy
    assert "not the API's shape" in detail
    await jev.aclose()


async def test_the_window_is_not_guessed(jev):
    """TypeSafe publishes no context size on the wire, and a number written
    here would go stale in silence. The binding's `context:` is the answer."""
    assert await jev.context_for("jev-latest") is None


class _CapturingStore(NullStore):
    """Keeps every event a run appends; `events` is the store's own reader."""

    def __init__(self):
        super().__init__()
        self.captured = []

    def append(self, event):
        self.captured.append(event)


async def test_a_decision_routes_a_graph(monkeypatch):
    """End to end through an ordinary agent node: the answer lands as JSON, the
    output path picks the choice, and the router branches on it -- the way a
    graph reads any other model. Nothing in the graph names the provider, and
    the run record says which inherited setting the model never saw."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-not-a-real-key")
    graph = GraphSpec.model_validate(
        {
            "name": "shape",
            "entry": "judge",
            "nodes": [
                {
                    "id": "judge",
                    "type": "agent",
                    "role": "judge",
                    "system": "You judge proposals.",
                    "prompt": "Proposal: {{ input.proposal }}",
                    "params": {"questions": QUESTIONS},
                    "output": {"as": "verdict", "format": "json", "path": "verdict.choice"},
                    "next": "route",
                },
                {
                    "id": "route",
                    "type": "router",
                    "branches": [{"when": "verdict == 'NARROW'", "to": "narrow", "label": "too big"}],
                    "default": "build",
                },
                {"id": "narrow", "type": "agent", "role": "narrower", "prompt": "send it back"},
                {"id": "build", "type": "agent", "role": "builder", "prompt": "build it"},
            ],
        }
    )
    binding = BindingSpec.model_validate(
        {
            "name": "decide",
            "providers": {
                "jev": {"type": "typesafe"},
                "fake": {"type": "mock", "options": {"responses": {"narrower": "sent back", "builder": "built"}}},
            },
            "default": {"provider": "fake", "model": "mock-model"},
            "roles": {"judge": {"provider": "jev", "model": "jev-latest", "params": {"max_tokens": 600}}},
        }
    )
    seen: dict = {}
    store = _CapturingStore()
    async with ProviderPool(binding) as pool:
        _mock_client(pool.get("jev"), _decided(seen))
        result = await execute(graph, binding, pool, store, input={"proposal": "add dark mode"})

    assert result.status == "completed"
    assert result.path == ["judge", "route", "narrow"]
    assert result.outputs["judge"] == "NARROW"
    assert result.outputs["narrow"] == "sent back"
    assert seen["body"]["state"] == "You judge proposals.\n\nProposal: add dark mode"

    finished = {e.node_id: e.data for e in store.captured if e.type == "node_finished"}
    assert finished["judge"]["ignored_params"] == ["max_tokens"]
    assert "ignored_params" not in finished["narrow"]
