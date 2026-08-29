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


def test_a_local_engine_is_preferred_over_the_metered_one(monkeypatch):
    """DESIGN.md principle 3: local first. The reason it gives is economic --
    a 24/7 resident has to be able to run without worrying about token spend --
    so a machine with both a Claude credential and a local server answering
    must not default to the metered one.

    Both are still declared. Only which one an unattended `init` binds to the
    default role is at stake, and `poieo config use` moves it in one command.
    """
    _serves(monkeypatch, {"http://localhost:11434/api/tags": OLLAMA_TAGS})

    async def _found():
        return ("claude-opus-5",)

    monkeypatch.setattr(detect_module, "_claude_models", _found)

    found = detect()

    assert [e.key for e in found] == ["ollama", "claude"]
    # ...and the whole pool is still there for a role to name.
    assert {e.key for e in found} == {"ollama", "claude"}


# -- what an endpoint says about each model, beyond its name -----------------

OLLAMA_DETAILED = {
    "models": [
        {
            "name": "qwen3.5:latest",
            "details": {
                "parameter_size": "9.0B",
                "quantization_level": "Q4_K_M",
                "context_length": 262144,
            },
            "capabilities": ["completion", "vision"],
        }
    ]
}

# OpenRouter's shape, and the only listing in the wild that carries a price.
# Per token on the wire, which is what makes it unreadable without converting.
ROUTED = {
    "data": [
        {
            "id": "qwen/qwen3.8-flash",
            "context_length": 1000000,
            "pricing": {"prompt": "0.00000015", "completion": "0.00000047"},
        }
    ]
}


async def test_a_local_model_reports_what_it_costs_in_memory_not_money(monkeypatch):
    """Ollama charges nothing per token, so there is no price to report -- and
    what a local model actually costs is the size and quantization it says."""
    _serves(monkeypatch, {"http://localhost:11434/api/tags": OLLAMA_DETAILED})

    served = await detect_module.catalogue_for("ollama", "http://localhost:11434")

    assert served[0].id == "qwen3.5:latest"
    assert (served[0].size, served[0].quantization) == ("9.0B", "Q4_K_M")
    assert served[0].context == 262144
    assert served[0].capabilities == ("completion", "vision")
    assert served[0].price is None


async def test_a_published_price_is_reported_per_million_tokens(monkeypatch):
    """`0.00000015` is not a number anybody compares at a glance. The endpoint
    is still the only source -- this converts what it said, and invents none."""
    _serves(monkeypatch, {"http://x/v1/models": ROUTED})

    served = await detect_module.catalogue_for("openai_compatible", "http://x/v1")

    assert served[0].price == (0.15, 0.47)
    assert served[0].context == 1000000


async def test_an_endpoint_that_publishes_no_price_says_nothing_rather_than_zero(
    monkeypatch,
):
    """vLLM, LM Studio and llama.cpp all answer the same listing with no rates
    on it. Zero would read as free, which is the one wrong answer available."""
    _serves(monkeypatch, {"http://x/v1/models": LMSTUDIO_MODELS})

    served = await detect_module.catalogue_for("openai_compatible", "http://x/v1")

    assert served[0].price is None
    assert served[0].context is None


async def test_a_half_priced_entry_is_not_half_reported(monkeypatch):
    """A listing with a prompt rate and no completion rate cannot be shown as
    a price, and showing the half that is there would read as the whole."""
    half = {"data": [{"id": "m", "pricing": {"prompt": "0.000001"}}]}
    _serves(monkeypatch, {"http://x/v1/models": half})

    served = await detect_module.catalogue_for("openai_compatible", "http://x/v1")

    assert served[0].price is None


async def test_one_malformed_entry_does_not_empty_the_listing(monkeypatch):
    """The rest of what the server said is still true."""
    mixed = {"data": [{"id": "good"}, {"nope": 1}, {"id": "also-good"}]}
    _serves(monkeypatch, {"http://x/v1/models": mixed})

    served = await detect_module.catalogue_for("openai_compatible", "http://x/v1")

    assert [m.id for m in served] == ["good", "also-good"]


async def test_models_for_is_the_same_listing_read_for_its_names(monkeypatch):
    """One request, one place that knows where to send it. `init` and
    `config use` only ever wanted names, and still get exactly those."""
    _serves(monkeypatch, {"http://localhost:11434/api/tags": OLLAMA_DETAILED})

    assert await detect_module.models_for("ollama", "http://localhost:11434") == (
        "qwen3.5:latest",
    )


async def test_a_type_that_cannot_be_asked_has_an_empty_catalogue():
    """`mock` answers from the binding file, so there is nothing to ask."""
    assert await detect_module.catalogue_for("mock", None) == ()
    assert not detect_module.askable("mock")


async def test_the_cap_is_a_default_a_catalogue_can_lift(monkeypatch):
    """`init` wants enough to fill a picker; a panel whose whole job is the
    catalogue wants all of it. Forty of three hundred shown without a word
    reads as all of them, which is the one thing a listing must not do."""
    many = {"data": [{"id": f"m{n}"} for n in range(120)]}
    _serves(monkeypatch, {"http://x/v1/models": many})

    capped = await detect_module.catalogue_for("openai_compatible", "http://x/v1")
    whole = await detect_module.catalogue_for(
        "openai_compatible", "http://x/v1", limit=None
    )

    assert len(capped) == detect_module.MODEL_CAP
    assert len(whole) == 120


def test_only_a_local_backend_lists_what_is_on_this_machine():
    """Two listings that look identical and mean different things: Ollama's is
    `ollama list` -- pulled, here, ready -- and OpenRouter's is a catalogue of
    what it would route to for money, with nothing here yet."""
    assert detect_module.lists_installed("ollama")
    assert not detect_module.lists_installed("openai_compatible")
    assert not detect_module.lists_installed("anthropic")
