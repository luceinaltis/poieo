"""What detection finds on a machine, and what it refuses to guess."""

import types

import httpx
import pytest

from poieo import detect as detect_module
from poieo.detect import CANDIDATES, detect


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
        types.SimpleNamespace(
            AsyncClient=fake, RequestError=httpx.RequestError, InvalidURL=httpx.InvalidURL, URL=httpx.URL
        ),
    )


def _guarded(monkeypatch, answers: dict[str, object], key: str):
    """Endpoints that answer only when the request carries ``key``.

    What every hosted endpoint does, and what a vLLM started with `--api-key`
    does: 401 to an unauthenticated listing. An endpoint like this is exactly
    the one somebody reaches for `--key-env` to add.
    """
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        if request.headers.get("authorization") != f"Bearer {key}":
            return httpx.Response(401, json={"error": "missing or invalid api key"})
        answer = answers.get(str(request.url))
        if answer is None:
            raise httpx.ConnectError("nothing listening", request=request)
        return httpx.Response(200, json=answer)

    def fake(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return httpx.AsyncClient(*args, **kwargs)

    monkeypatch.setattr(
        detect_module,
        "httpx",
        types.SimpleNamespace(
            AsyncClient=fake, RequestError=httpx.RequestError, InvalidURL=httpx.InvalidURL, URL=httpx.URL
        ),
    )
    return seen


def _no_claude(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(detect_module, "_claude_models", _nothing)


async def _nothing(api_key_env=None):
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

    async def _found(api_key_env=None):
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

    async def _found(api_key_env=None):
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

    served = (await detect_module.catalogue_for("ollama", "http://localhost:11434")).models

    assert served[0].id == "qwen3.5:latest"
    assert (served[0].size, served[0].quantization) == ("9.0B", "Q4_K_M")
    assert served[0].context == 262144
    assert served[0].capabilities == ("completion", "vision")
    assert served[0].price is None


async def test_a_published_price_is_reported_per_million_tokens(monkeypatch):
    """`0.00000015` is not a number anybody compares at a glance. The endpoint
    is still the only source -- this converts what it said, and invents none."""
    _serves(monkeypatch, {"http://x/v1/models": ROUTED})

    served = (await detect_module.catalogue_for("openai_compatible", "http://x/v1")).models

    assert served[0].price == (0.15, 0.47)
    assert served[0].context == 1000000


async def test_an_endpoint_that_publishes_no_price_says_nothing_rather_than_zero(
    monkeypatch,
):
    """vLLM, LM Studio and llama.cpp all answer the same listing with no rates
    on it. Zero would read as free, which is the one wrong answer available."""
    _serves(monkeypatch, {"http://x/v1/models": LMSTUDIO_MODELS})

    served = (await detect_module.catalogue_for("openai_compatible", "http://x/v1")).models

    assert served[0].price is None
    assert served[0].context is None


async def test_a_half_priced_entry_is_not_half_reported(monkeypatch):
    """A listing with a prompt rate and no completion rate cannot be shown as
    a price, and showing the half that is there would read as the whole."""
    half = {"data": [{"id": "m", "pricing": {"prompt": "0.000001"}}]}
    _serves(monkeypatch, {"http://x/v1/models": half})

    served = (await detect_module.catalogue_for("openai_compatible", "http://x/v1")).models

    assert served[0].price is None


async def test_one_malformed_entry_does_not_empty_the_listing(monkeypatch):
    """The rest of what the server said is still true."""
    mixed = {"data": [{"id": "good"}, {"nope": 1}, {"id": "also-good"}]}
    _serves(monkeypatch, {"http://x/v1/models": mixed})

    served = (await detect_module.catalogue_for("openai_compatible", "http://x/v1")).models

    assert [m.id for m in served] == ["good", "also-good"]


async def test_models_for_is_the_same_listing_read_for_its_names(monkeypatch):
    """One request, one place that knows where to send it. `init` and
    `config use` only ever wanted names, and still get exactly those."""
    _serves(monkeypatch, {"http://localhost:11434/api/tags": OLLAMA_DETAILED})

    assert await detect_module.models_for("ollama", "http://localhost:11434") == ("qwen3.5:latest",)


async def test_a_type_that_cannot_be_asked_has_an_empty_catalogue():
    """`mock` answers from the binding file, so there is nothing to ask."""
    assert (await detect_module.catalogue_for("mock", None)).models == ()
    assert not detect_module.askable("mock")


async def test_the_cap_is_a_default_a_catalogue_can_lift(monkeypatch):
    """`init` wants enough to fill a picker; a panel whose whole job is the
    catalogue wants all of it. Forty of three hundred shown without a word
    reads as all of them, which is the one thing a listing must not do."""
    many = {"data": [{"id": f"m{n}"} for n in range(120)]}
    _serves(monkeypatch, {"http://x/v1/models": many})

    capped = (await detect_module.catalogue_for("openai_compatible", "http://x/v1")).models
    whole = (await detect_module.catalogue_for("openai_compatible", "http://x/v1", limit=None)).models

    assert len(capped) == detect_module.MODEL_CAP
    assert len(whole) == 120


def test_only_a_local_backend_lists_what_is_on_this_machine():
    """Two listings that look identical and mean different things: Ollama's is
    `ollama list` -- pulled, here, ready -- and OpenRouter's is a catalogue of
    what it would route to for money, with nothing here yet."""
    assert detect_module.lists_installed("ollama")
    assert not detect_module.lists_installed("openai_compatible")
    assert not detect_module.lists_installed("anthropic")


def test_an_endpoint_is_named_by_something_a_person_recognises():
    """`openai_compatible` is four products in a trench coat. The address is
    what tells them apart, and `CANDIDATES` already wrote the names down."""
    assert detect_module.label_for("ollama") == "Ollama"
    assert detect_module.label_for("anthropic") == "Claude API"
    assert detect_module.label_for("openai_compatible", "https://openrouter.ai/api/v1") == "OpenRouter"
    assert detect_module.label_for("openai_compatible", "http://localhost:1234/v1") == "LM Studio"


def test_an_address_nobody_wrote_down_is_not_guessed_at():
    """A registry of every hosted endpoint would go stale, and recognising one
    wrongly is worse than not recognising it. None means the panel falls back
    to what it says today."""
    assert detect_module.label_for("openai_compatible", "https://unknown.example/v1") is None
    assert detect_module.label_for("openai_compatible", None) is None
    assert detect_module.label_for("mock") is None


def test_vllm_and_sglang_share_one_label_because_they_share_a_port():
    """Their listings are the same shape. Saying `vLLM` of an SGLang server
    would be worse than saying both."""
    assert detect_module.label_for("openai_compatible", "http://localhost:8000/v1") == "vLLM / SGLang"


# The two that share a default port, answering listings of the same shape. The
# only thing that tells them apart is the name each writes into `owned_by` --
# verified in their own source, not guessed:
#   vLLM       vllm/entrypoints/openai/engine/protocol.py  `owned_by: str = "vllm"`
#   SGLang     sglang/srt/entrypoints/openai/protocol.py   `owned_by: str = "sglang"`
VLLM = {"data": [{"id": "facebook/opt-125m", "owned_by": "vllm", "max_model_len": 2048}]}
SGLANG = {"data": [{"id": "facebook/opt-125m", "owned_by": "sglang"}]}


async def test_a_server_that_names_itself_is_taken_at_its_own_word(monkeypatch):
    """The address cannot tell vLLM from SGLang -- they share port 8000 -- so
    nothing about where it is answers the question. What the server says on
    its own listing does."""
    _serves(monkeypatch, {"http://localhost:8000/v1/models": VLLM})

    answered = await detect_module.catalogue_for("openai_compatible", "http://localhost:8000/v1")

    assert answered.server == "vLLM"
    assert detect_module.label_for("openai_compatible", "http://localhost:8000/v1", answered.server) == "vLLM"


async def test_the_same_address_says_sglang_when_sglang_is_the_one_there(monkeypatch):
    """Same port, same listing shape, different server. This is the case a
    label read off the address gets wrong every time."""
    _serves(monkeypatch, {"http://localhost:8000/v1/models": SGLANG})

    answered = await detect_module.catalogue_for("openai_compatible", "http://localhost:8000/v1")

    assert answered.server == "SGLang"


async def test_a_server_moved_off_its_usual_port_is_still_itself(monkeypatch):
    """Which is the other half of asking rather than inferring: an address
    nobody wrote down would have had no label at all."""
    _serves(monkeypatch, {"http://box.local:9999/v1/models": SGLANG})

    answered = await detect_module.catalogue_for("openai_compatible", "http://box.local:9999/v1")

    assert answered.server == "SGLang"
    assert detect_module.label_for("openai_compatible", "http://box.local:9999/v1", answered.server) == "SGLang"


async def test_owned_by_is_only_read_as_a_server_when_a_server_is_known_to_say_it(
    monkeypatch,
):
    """`owned_by` means "who owns the model" in the OpenAI schema -- OpenAI's
    own API answers `openai` and `system` with it. Reading any value as a
    product name would label a proxy "openai"."""
    owned = {"data": [{"id": "gpt-4", "owned_by": "openai"}]}
    _serves(monkeypatch, {"http://x/v1/models": owned})

    answered = await detect_module.catalogue_for("openai_compatible", "http://x/v1")

    assert answered.server is None


async def test_what_the_server_said_beats_what_the_address_suggests(monkeypatch):
    """A binding may point `http://localhost:1234/v1` at anything at all. The
    address is a guess about what is listening; the listing is an answer."""
    _serves(monkeypatch, {"http://localhost:1234/v1/models": VLLM})

    answered = await detect_module.catalogue_for("openai_compatible", "http://localhost:1234/v1")

    # Without the listing this address reads as LM Studio.
    assert detect_module.label_for("openai_compatible", "http://localhost:1234/v1") == "LM Studio"
    assert detect_module.label_for("openai_compatible", "http://localhost:1234/v1", answered.server) == "vLLM"


# -- an engine at an address nobody guessed -----------------------------------
#
# `CANDIDATES` knows four ports on this machine. An inference server is
# routinely somewhere else -- a vLLM on 8001 because 8000 was taken, an Ollama
# on the desktop under the desk, a shared box in an office -- and there was no
# way to reach any of them but opening the binding file by hand.
#
# `ask` takes the address and finds out what is there, rather than making the
# user classify it: the two listing shapes are tried, and whichever answers
# says which backend it is.


@pytest.mark.asyncio
async def test_an_address_that_speaks_ollama_is_found_to_be_one(monkeypatch):
    _serves(monkeypatch, {"http://box:11434/api/tags": {"models": [{"name": "qwen3:32b"}]}})

    engine = await detect_module.ask("http://box:11434")

    assert engine is not None
    assert (engine.type, engine.models) == ("ollama", ("qwen3:32b",))
    assert engine.base_url == "http://box:11434"


@pytest.mark.asyncio
async def test_an_address_that_speaks_openai_is_found_to_be_one(monkeypatch):
    _serves(monkeypatch, {"http://box:8001/v1/models": {"data": [{"id": "qwen3-32b"}]}})

    engine = await detect_module.ask("http://box:8001/v1")

    assert engine is not None
    assert (engine.type, engine.models) == ("openai_compatible", ("qwen3-32b",))


@pytest.mark.asyncio
async def test_the_v1_everybody_forgets_is_tried_too(monkeypatch):
    """`http://box:8001` is what a person reads off a terminal; the OpenAI
    shape lives one segment further down. Refusing the address they have is
    making them debug a URL to answer a question this can answer itself."""
    _serves(monkeypatch, {"http://box:8001/v1/models": {"data": [{"id": "qwen3-32b"}]}})

    engine = await detect_module.ask("http://box:8001")

    assert engine is not None
    assert engine.base_url == "http://box:8001/v1"


@pytest.mark.asyncio
async def test_a_server_that_names_itself_is_named_that(monkeypatch):
    """vLLM and SGLang share a port and a listing shape. What separates them is
    what they say about themselves, and that is what the name comes from."""
    _serves(
        monkeypatch,
        {"http://box:8001/v1/models": {"data": [{"id": "m", "owned_by": "sglang"}]}},
    )

    engine = await detect_module.ask("http://box:8001/v1")

    assert engine is not None
    assert engine.known_as == "SGLang"
    assert engine.key == "sglang"


@pytest.mark.asyncio
async def test_an_address_with_nothing_on_it_is_not_an_engine(monkeypatch):
    """The rule `probe` holds: naming an endpoint that serves nothing writes a
    binding that fails on the project's first run."""
    _serves(monkeypatch, {})

    assert await detect_module.ask("http://box:9999") is None


@pytest.mark.asyncio
async def test_an_address_is_named_after_its_host_when_it_says_nothing(monkeypatch):
    """Something has to go in `providers:`, and a host a person typed is a name
    they will recognise -- where `openai_compatible` would tell them nothing."""
    _serves(monkeypatch, {"http://gpu-box:8080/v1/models": {"data": [{"id": "m"}]}})

    engine = await detect_module.ask("http://gpu-box:8080/v1")

    assert engine is not None
    assert engine.key == "gpu-box"


# -- the key the caller named -------------------------------------------------
#
# An endpoint that wants a key answers 401 to an unauthenticated listing, and
# `Catalogue()` is what detection returns for a 401 -- which reads, all the way
# up, as "nothing usable answered". Every hosted endpoint is one of these, and
# so is a vLLM started with `--api-key`; they are the whole reason `--key-env`
# and the board's key field exist, and asking without the key made them the one
# thing neither could add.


@pytest.mark.asyncio
async def test_an_endpoint_that_wants_a_key_is_asked_with_it(monkeypatch):
    monkeypatch.setenv("OFFICE_API_KEY", "sk-real")
    _guarded(monkeypatch, {"http://gpu-box:8001/v1/models": {"data": [{"id": "qwen3-32b"}]}}, "sk-real")

    answered = await detect_module.catalogue_for(
        "openai_compatible", "http://gpu-box:8001/v1", api_key_env="OFFICE_API_KEY"
    )

    assert [m.id for m in answered.models] == ["qwen3-32b"]


@pytest.mark.asyncio
async def test_the_same_endpoint_asked_without_one_still_answers_nothing(monkeypatch):
    """The half that was already true, kept: silence is what a 401 means to a
    caller that named no variable, and detection still never raises."""
    monkeypatch.setenv("OFFICE_API_KEY", "sk-real")
    _guarded(monkeypatch, {"http://gpu-box:8001/v1/models": {"data": [{"id": "qwen3-32b"}]}}, "sk-real")

    answered = await detect_module.catalogue_for("openai_compatible", "http://gpu-box:8001/v1")

    assert answered.models == ()


@pytest.mark.asyncio
async def test_a_variable_that_is_not_set_sends_no_header_and_does_not_raise(monkeypatch):
    """Detection asks and never decides. A name with nothing behind it is a
    question for whoever typed it, not an exception out of a probe -- and
    `credential_for` is deliberately not used here for that reason."""
    monkeypatch.delenv("OFFICE_API_KEY", raising=False)
    seen = _guarded(monkeypatch, {"http://gpu-box:8001/v1/models": {"data": [{"id": "m"}]}}, "sk-real")

    answered = await detect_module.catalogue_for(
        "openai_compatible", "http://gpu-box:8001/v1", api_key_env="OFFICE_API_KEY"
    )

    assert answered.models == ()
    assert seen == [None]


@pytest.mark.asyncio
async def test_ask_carries_the_key_through_every_attempt_and_writes_it_down(monkeypatch):
    """`ask` tries three addresses. The key belongs to all of them, and the
    engine it returns has to carry the variable's name -- otherwise the caller
    has to graft it back on afterwards and the two can disagree."""
    monkeypatch.setenv("OFFICE_API_KEY", "sk-real")
    _guarded(monkeypatch, {"http://gpu-box:8001/v1/models": {"data": [{"id": "qwen3-32b"}]}}, "sk-real")

    engine = await detect_module.ask("http://gpu-box:8001", key_env="OFFICE_API_KEY")

    assert engine is not None
    assert engine.models == ("qwen3-32b",)
    assert engine.base_url == "http://gpu-box:8001/v1"
    assert engine.api_key_env == "OFFICE_API_KEY"


@pytest.mark.asyncio
async def test_an_ollama_behind_a_key_is_asked_with_it_too(monkeypatch):
    """The rule is the endpoint's, not the shape's. An Ollama behind a proxy
    that wants a key lists like any other."""
    monkeypatch.setenv("OFFICE_API_KEY", "sk-real")
    _guarded(monkeypatch, {"http://box:11434/api/tags": {"models": [{"name": "qwen3:32b"}]}}, "sk-real")

    engine = await detect_module.ask("http://box:11434", key_env="OFFICE_API_KEY")

    assert engine is not None
    assert (engine.type, engine.models) == ("ollama", ("qwen3:32b",))


# -- an address that is not one ----------------------------------------------
#
# `ask` is the first caller to hand detection a string somebody typed, and a
# typed address has typos in it. `httpx` refuses a malformed one by raising --
# `InvalidURL` for a port that is not a number, and idna's own `UnicodeError`
# for a hostname it cannot encode -- and neither is a `RequestError`, so both
# went straight past the one clause that was catching. Nothing downstream
# catches them either: the route is on a bare Starlette with no exception
# handlers, so a typo was a 500, and `_guarded` in the CLI catches PoieoError
# and OSError, so it was a traceback against a decorator whose docstring
# promises never to print one.


@pytest.mark.asyncio
@pytest.mark.parametrize("typo", ["http://box:80O1", "http://box:notaport", "http://xn--a.com:8001"])
async def test_an_address_that_cannot_be_asked_is_an_answer_and_not_a_crash(monkeypatch, typo):
    """The rule this module opens with: every outcome is a return value."""
    _serves(monkeypatch, {})

    assert await detect_module.ask(typo) is None
    assert await detect_module.catalogue_for("openai_compatible", typo) == detect_module.Catalogue()


@pytest.mark.parametrize(
    "typo,names",
    [
        ("http://box:80O1", "port"),
        ("http://box:notaport", "port"),
        ("http://xn--a.com:8001", "xn--a.com"),
    ],
)
def test_why_an_address_cannot_be_asked_is_something_the_caller_can_say(typo, names):
    """Silence is the right answer *inside* detection and the wrong one at the
    surface: "nothing usable answered at http://box:80O1" is true, and has the
    reader checking whether their server is up. The two callers that take a
    typed address ask this first and say what is wrong with it."""
    said = detect_module.unaskable(typo)

    assert said is not None and names in said


def test_an_address_that_is_merely_unreachable_is_not_refused_here():
    """Only the shape. Whether anything is listening is what asking is for, and
    a check that guessed would refuse the office box on a night it was off."""
    for fine in ("http://gpu-box:8001/v1", "http://localhost:11434", "http://[::1]:8000", "http://사무실:8001"):
        assert detect_module.unaskable(fine) is None, fine


def test_what_is_wrong_is_said_in_the_reader_s_own_words(monkeypatch):
    """idna's are about a codepoint at a position in a string it decoded, and
    name nothing that was typed. `poieo config add http://xn--gpu-box.local`
    was told about `U+1C7E at position 3 of 'gp?u'`."""
    said = detect_module.unaskable("http://xn--gpu-box.local:8001")

    assert said is not None
    assert "xn--gpu-box.local" in said
    assert "Codepoint" not in said and "position" not in said


def test_an_address_that_is_only_a_slash_is_still_quoted_back(monkeypatch):
    """Every other refusal here names what was typed; this one used to be the
    bare fragment "an empty address"."""
    assert detect_module.unaskable("/") == "/ is not an address"
