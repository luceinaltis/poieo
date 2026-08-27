"""What detection finds on a machine, and what it refuses to guess."""

import types

import httpx
import pytest

from poieo import detect as detect_module
from poieo.detect import CANDIDATES, Engine, detect


def _serves(monkeypatch, answers: dict[str, object]):
    """Stand in for every HTTP endpoint detection knows how to ask.

    ``answers`` maps a full URL onto what that address does: a dict is JSON it
    answers with, a string is a non-JSON body, and an Exception is raised as
    though the address were not listening. An address not named is not
    listening.

    Swapped in as detect.py's whole view of httpx rather than by mutating the
    real module, so a test cannot reach past this into anyone else's client.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        answer = answers.get(str(request.url))
        if answer is None:
            raise httpx.ConnectError("nothing listening", request=request)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, dict):
            return httpx.Response(200, json=answer)
        return httpx.Response(200, text=str(answer))

    def fake(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    monkeypatch.setattr(
        detect_module,
        "httpx",
        types.SimpleNamespace(AsyncClient=fake, RequestError=httpx.RequestError),
    )


def _no_claude(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(detect_module, "_claude_models", _nothing)


async def _nothing():
    return ()


OLLAMA_TAGS = {"models": [{"name": "qwen3:32b"}, {"name": "llama3.2:3b"}]}
LMSTUDIO_MODELS = {"data": [{"id": "qwen2.5-coder-7b"}]}


def test_a_bare_machine_finds_nothing(monkeypatch):
    _no_claude(monkeypatch)
    _serves(monkeypatch, {})
    assert detect() == []


def test_an_answering_ollama_is_found_with_the_models_it_reports(monkeypatch):
    _no_claude(monkeypatch)
    _serves(monkeypatch, {"http://localhost:11434/api/tags": OLLAMA_TAGS})

    found = detect()

    assert [e.key for e in found] == ["ollama"]
    assert found[0].type == "ollama"
    assert found[0].base_url == "http://localhost:11434"
    # In the server's own order, which is what `ollama list` shows the user.
    assert found[0].models == ("qwen3:32b", "llama3.2:3b")


def test_an_openai_compatible_server_is_found_on_its_own_port(monkeypatch):
    _no_claude(monkeypatch)
    _serves(monkeypatch, {"http://localhost:1234/v1/models": LMSTUDIO_MODELS})

    found = detect()

    assert [e.key for e in found] == ["lmstudio"]
    assert found[0].type == "openai_compatible"
    # The base_url a binding needs is the /v1 root, not the /models path.
    assert found[0].base_url == "http://localhost:1234/v1"
    assert found[0].models == ("qwen2.5-coder-7b",)


def test_every_engine_that_answers_is_returned(monkeypatch):
    """The point of detection: a pool to bind roles against, not one winner."""
    _no_claude(monkeypatch)
    _serves(
        monkeypatch,
        {
            "http://localhost:11434/api/tags": OLLAMA_TAGS,
            "http://localhost:1234/v1/models": LMSTUDIO_MODELS,
            "http://localhost:8000/v1/models": {"data": [{"id": "qwen"}]},
        },
    )

    found = detect()

    assert [e.key for e in found] == ["ollama", "lmstudio", "vllm"]


def test_engines_come_back_in_a_fixed_order(monkeypatch):
    """A picker that reshuffles between runs is a picker nobody can trust."""
    _no_claude(monkeypatch)
    _serves(
        monkeypatch,
        {
            "http://localhost:8000/v1/models": {"data": [{"id": "a"}]},
            "http://localhost:11434/api/tags": OLLAMA_TAGS,
        },
    )

    order = [c.key for c in CANDIDATES]
    found = [e.key for e in detect()]
    assert found == sorted(found, key=order.index)


def test_a_server_that_answers_with_something_else_is_not_an_engine(monkeypatch):
    """A captive portal or a proxy answers 200 with HTML. That is not a model."""
    _no_claude(monkeypatch)
    _serves(monkeypatch, {"http://localhost:11434/api/tags": "<html>hello</html>"})
    assert detect() == []


def test_an_engine_answering_with_no_models_is_not_offered(monkeypatch):
    """An Ollama with nothing pulled cannot serve a binding, so it is not a
    choice -- naming it would produce a project that fails on its first run."""
    _no_claude(monkeypatch)
    _serves(monkeypatch, {"http://localhost:11434/api/tags": {"models": []}})
    assert detect() == []


def test_one_dead_port_does_not_hide_a_live_one(monkeypatch):
    _no_claude(monkeypatch)
    _serves(
        monkeypatch,
        {
            "http://localhost:1234/v1/models": httpx.ReadTimeout("slow"),
            "http://localhost:11434/api/tags": OLLAMA_TAGS,
        },
    )
    assert [e.key for e in detect()] == ["ollama"]


def test_claude_is_found_through_the_sdk_and_named_by_it(monkeypatch):
    _serves(monkeypatch, {})

    async def _found():
        return ("claude-opus-5", "claude-sonnet-5")

    monkeypatch.setattr(detect_module, "_claude_models", _found)

    found = detect()

    assert [e.key for e in found] == ["claude"]
    assert found[0].base_url is None  # the SDK knows where it lives
    assert "claude-opus-5" in found[0].models


def test_claude_without_a_credential_is_not_offered(monkeypatch):
    """The SDK refuses before any network I/O when it can resolve no
    credential, and that refusal is an answer -- not a crash in front of a
    user who is being shown a list."""
    import anthropic

    def refuses(**kwargs):
        raise anthropic.AnthropicError("no api key")

    monkeypatch.setattr(anthropic, "AsyncAnthropic", refuses)
    _serves(monkeypatch, {})

    # The real _claude runs here; only the SDK is stood in for.
    assert [e.key for e in detect()] == []


def test_mock_is_never_a_detected_engine(monkeypatch):
    """mock answers from a script. It is a thing you ask for, never a thing
    found on your machine -- a project that picked it by accident would run
    all night and answer with invented text."""
    _no_claude(monkeypatch)
    _serves(monkeypatch, {"http://localhost:11434/api/tags": OLLAMA_TAGS})
    assert all(e.type != "mock" for e in detect())
    assert all(c.key != "mock" for c in CANDIDATES)


@pytest.mark.parametrize("candidate", CANDIDATES)
def test_every_candidate_names_a_real_provider_type(candidate):
    """A candidate whose type no provider implements would be found and then
    fail to load -- caught here rather than on the user's first run."""
    from poieo.binding import KNOWN_PROVIDER_TYPES

    assert candidate.type in KNOWN_PROVIDER_TYPES


@pytest.mark.parametrize("candidate", CANDIDATES)
def test_every_candidate_can_actually_be_asked(candidate):
    """A candidate detection cannot read is a candidate that never answers.
    `anthropic` goes through the SDK; everything else needs a reader."""
    from poieo.detect import _READERS

    assert candidate.type == "anthropic" or candidate.type in _READERS


async def test_a_declared_provider_is_asked_the_same_way_detection_asks(monkeypatch):
    """`poieo config models` reaches models_for() from a binding rather than a
    candidate. Same type, same address, same answer -- or the board and the
    binding eventually disagree about what a provider serves."""
    from poieo.detect import models_for

    _serves(monkeypatch, {"http://elsewhere:9999/api/tags": OLLAMA_TAGS})

    # An address no CANDIDATE names: the reader is chosen by type.
    assert await models_for("ollama", "http://elsewhere:9999") == (
        "qwen3:32b",
        "llama3.2:3b",
    )


async def test_a_type_with_nothing_to_ask_answers_empty(monkeypatch):
    """`mock` serves from its own file and a caller-registered backend has no
    listing convention. Neither is an error -- there is just nothing to say."""
    from poieo.detect import models_for

    _serves(monkeypatch, {})
    assert await models_for("mock", None) == ()
    assert await models_for("something_registered_later", "http://x") == ()
