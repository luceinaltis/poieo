"""What this machine can actually answer with.

Detection **asks, and never decides.** It returns every engine that answered
and the models each one reported; choosing among them, and writing anything
down, belongs to the caller. Nothing here touches a file.

It also runs **once**, at ``poieo init``. Run time reads files, never ports --
a binding names an endpoint because somebody wrote it there, not because a
port happened to answer tonight.

``mock`` is deliberately not a candidate. It answers from a script, so a
project that fell back to it would run all night and produce invented text.
Asking for it stays a thing the user does on purpose, with
``-b models/mock.yaml``.

Design: docs/storage.md
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

import httpx

# Per address, with all of them asked at once: init has to feel instant on a
# machine with nothing listening, and that is the common case.
HTTP_TIMEOUT = 1.5

# Enough to fill a picker. A server offering hundreds is a catalogue, not a
# choice, and the binding file is where the full name gets typed anyway.
#
# The default and not the rule: a caller whose whole job **is** the catalogue
# passes `limit=None`, because forty of three hundred and ninety-six shown
# without a word reads as all of them.
MODEL_CAP = 40


@dataclass(frozen=True)
class Served:
    """One model an endpoint says it has, and whatever else it said about it.

    Every field but ``id`` is **None when the endpoint did not say**, and none
    of them is ever filled in from anywhere else. That is the same rule the
    catalogue itself follows: a fact written down here would be wrong the week
    after, so nothing is written down and silence stays silence.

    ``price`` in particular. `docs/runtime.md` refuses a price table in this
    repository -- "nothing in poieo knows what a model charges, and a price
    table checked in here would be wrong the week after it was written" -- and
    this does not add one. OpenRouter publishes per-token rates on the same
    listing it publishes model ids on; where an endpoint does, they are
    reported, and where it does not there is a blank rather than a guess.
    """

    id: str
    # Tokens the model holds, when the endpoint publishes it.
    context: int | None = None
    # Ollama's own words for a local build: "9.0B", "Q4_K_M". For a local
    # model these two are the price -- what it costs is memory, not money.
    size: str | None = None
    quantization: str | None = None
    capabilities: tuple[str, ...] = ()
    # USD per **million** tokens, (input, output). The wire unit everywhere
    # these are published is per token, which reads as 0.000000834 and cannot
    # be compared at a glance.
    price: tuple[float, float] | None = None


@dataclass(frozen=True)
class Catalogue:
    """What one endpoint answered with: its models, and who it said it was."""

    models: tuple[Served, ...] = ()
    # The product serving this, when it named itself -- see `_SAYS_ITS_NAME`.
    server: str | None = None


@dataclass(frozen=True)
class Engine:
    """One endpoint that answered, and the models it said it has."""

    # The name it takes in a binding's `providers:` block.
    key: str
    # What a person calls it.
    label: str
    # The provider type that will serve it.
    type: str
    models: tuple[str, ...]
    # None when the backend's own SDK knows where it lives -- see _claude.
    base_url: str | None = None


@dataclass(frozen=True)
class Candidate:
    """An address detection knows how to look at."""

    key: str
    label: str
    type: str
    # None means "not an address": asked through its own SDK instead.
    base_url: str | None = None


# Everything detection knows how to look for, in the order a picker shows them
# -- which is also the order an unattended `init` takes its answer from.
#
# Local servers lead, and the reason is DESIGN.md principle 3's own: a resident
# that runs around the clock has to be able to do it without anybody watching
# the token spend, so the metered endpoint is not what a project falls into by
# default. Every engine found is still declared either way; this decides only
# which one an unbound role reaches, and `poieo config use` moves that in one
# command.
CANDIDATES: tuple[Candidate, ...] = (
    Candidate("ollama", "Ollama", "ollama", "http://localhost:11434"),
    Candidate("lmstudio", "LM Studio", "openai_compatible", "http://localhost:1234/v1"),
    Candidate("vllm", "vLLM / SGLang", "openai_compatible", "http://localhost:8000/v1"),
    Candidate("llamacpp", "llama.cpp", "openai_compatible", "http://localhost:8080/v1"),
    Candidate("claude", "Claude API", "anthropic"),
)


def _number(value: Any) -> float | None:
    """A price as the wire gave it -- a string, on every endpoint that has one."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _priced(entry: dict[str, Any]) -> tuple[float, float] | None:
    """OpenRouter's `pricing` block, per million tokens.

    Per token on the wire (`"0.000000834"`), which is unreadable at a glance
    and incomparable between two models without counting zeroes. Absent on
    every other OpenAI-shaped server, and absent is the answer then.
    """
    pricing = entry.get("pricing")
    if not isinstance(pricing, dict):
        return None
    prompt, completion = _number(pricing.get("prompt")), _number(pricing.get("completion"))
    if prompt is None or completion is None:
        return None
    return (prompt * 1_000_000, completion * 1_000_000)


def _ollama_served(entry: dict[str, Any]) -> Served:
    """What a local Ollama publishes. No price: it does not charge per token,
    and what a local model actually costs is the memory in `size`."""
    details = entry.get("details")
    details = details if isinstance(details, dict) else {}
    capabilities = entry.get("capabilities")
    return Served(
        id=str(entry["name"]),
        context=details.get("context_length"),
        size=details.get("parameter_size"),
        quantization=details.get("quantization_level"),
        capabilities=tuple(str(c) for c in capabilities) if isinstance(capabilities, list) else (),
    )


def _openai_served(entry: dict[str, Any]) -> Served:
    """The OpenAI listing shape. `id` is all it promises; OpenRouter adds a
    context length and per-token rates on the same entry, and vLLM, LM Studio
    and llama.cpp add neither."""
    return Served(
        id=str(entry["id"]),
        context=entry.get("context_length"),
        price=_priced(entry),
    )


# How to ask an endpoint of each type what it serves: the path, the key holding
# the list, and how to read one entry off it. Keyed by **provider type**, not by
# address, because the question outlives detection -- a binding declares a type
# and a base_url, and `poieo config models` and the board ask the same way from
# there. Two copies of this would eventually look in two places.
_READERS: dict[str, tuple[str, str, Callable[[dict[str, Any]], Served]]] = {
    "ollama": ("/api/tags", "models", _ollama_served),
    "openai_compatible": ("/models", "data", _openai_served),
}

# The key on an entry that has to be there for it to be a model at all.
_IDENTIFIES = {"ollama": "name", "openai_compatible": "id"}

# Servers that write their own name into `owned_by` on every model they list,
# and the name a person calls each. Verified in their source rather than
# guessed -- the field means "who owns the model" in the OpenAI schema, and
# OpenAI's own API answers `openai` or `system` with it, so only values a
# server is *known* to use for itself are read as one:
#
#   vLLM        vllm/entrypoints/openai/engine/protocol.py  `owned_by: str = "vllm"`
#   SGLang      sglang/srt/entrypoints/openai/protocol.py   `owned_by: str = "sglang"`
#   llama.cpp   tools/server/server-context.cpp             `{"owned_by", "llamacpp"}`
#
# This is what tells vLLM from SGLang, which share a default port and answer
# listings of the same shape. It is the **server's** answer about itself, not
# a name somebody typed into a binding -- a config file says what its author
# believed, and the point of asking is to find out what is actually there.
_SAYS_ITS_NAME = {"vllm": "vLLM", "sglang": "SGLang", "llamacpp": "llama.cpp"}


def _server_named(entry: dict[str, Any]) -> str | None:
    """Which product this listing came from, if its entry says so."""
    owner = entry.get("owned_by")
    return _SAYS_ITS_NAME.get(owner) if isinstance(owner, str) else None


async def _listed(type_: str, base_url: str, limit: int | None) -> Catalogue:
    """Ask one HTTP address what it has, and who it says it is.

    Every outcome is a return value, never an exception -- including a 200
    that is not JSON, which is what a proxy or a captive portal answers with,
    and including an entry shaped in a way its own reader chokes on.
    """
    path, listing, read = _READERS[type_]
    identifier = _IDENTIFIES[type_]
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(f"{base_url}{path}")
    except httpx.RequestError:
        return Catalogue()
    if response.status_code >= 400:
        return Catalogue()
    try:
        served = response.json().get(listing)
    except ValueError:
        return Catalogue()
    if not isinstance(served, list):
        return Catalogue()

    # In the server's own order, which is the order the user already knows
    # from `ollama list`.
    out: list[Served] = []
    server: str | None = None
    for entry in served:
        if not isinstance(entry, dict) or not entry.get(identifier):
            continue
        server = server or _server_named(entry)
        try:
            out.append(read(entry))
        except Exception:
            # One malformed entry is not a reason to report an endpoint as
            # serving nothing; the rest of the listing is still true.
            continue
        if limit is not None and len(out) >= limit:
            break
    return Catalogue(tuple(out), server)


async def _claude_models() -> tuple[str, ...]:
    """What Claude serves, if this machine holds a credential the SDK accepts.

    Asked through the SDK rather than a URL, because it resolves an
    ``ANTHROPIC_API_KEY``, an auth token, or an ``ant auth login`` profile on
    its own -- and with none of them it refuses before any network I/O, which
    is what keeps init instant on a machine that has never seen a key.
    """
    import anthropic

    client = None
    try:
        client = anthropic.AsyncAnthropic(timeout=HTTP_TIMEOUT, max_retries=0)
        listed = await client.models.list(limit=MODEL_CAP)
        return tuple(str(model.id) for model in listed.data)
    except Exception:
        # Any refusal at all means "not available here". The caller is about to
        # show a list; a stack trace is not one of the options on it.
        return ()
    finally:
        if client is not None:
            await client.close()


def askable(type_: str) -> bool:
    """Whether an endpoint of this type can be asked what it serves.

    ``mock`` cannot -- it answers from the binding file itself -- and neither
    can a backend some caller registered, which has no listing convention we
    know. Silence from those two is a different fact from an endpoint that
    did not answer, and a listing that conflated them would read as a fault.
    """
    return type_ == "anthropic" or type_ in _READERS


async def catalogue_for(type_: str, base_url: str | None = None, limit: int | None = MODEL_CAP) -> Catalogue:
    """What an endpoint of this type, at this address, serves **right now**,
    with whatever else it said about each model.

    Empty when it cannot be reached, answers in a shape its type does not
    promise, or serves nothing at all. The one place that knows how each
    backend lists what it has, so detection, `poieo config models` and the
    board can never disagree about where to look -- which is why the richer
    answer lives here and `models_for` is a view of it rather than a second
    request with its own idea of where to send it.
    """
    if type_ == "anthropic":
        # The SDK's listing promises an id and nothing this cares about, and
        # asks for `MODEL_CAP` of them -- Anthropic serves far fewer than that,
        # so a caller wanting everything already has it.
        named = await _claude_models()
        return Catalogue(tuple(Served(id=name) for name in named[:limit]))
    if type_ not in _READERS or base_url is None:
        # A type with nothing to ask -- `mock` answers from its own file, and
        # an unknown backend registered by a caller has no listing convention.
        return Catalogue()
    return await _listed(type_, base_url, limit)


async def models_for(type_: str, base_url: str | None = None) -> tuple[str, ...]:
    """Just the ids, for the callers that only ever wanted a list of names --
    `init`, `config add`, and `config use`'s check that a model is really there."""
    return tuple(model.id for model in (await catalogue_for(type_, base_url)).models)


# Addresses whose product is worth naming, beyond the four `CANDIDATES`
# already knows by their default ports. Deliberately short: a registry of
# every hosted endpoint is a table that goes stale, and the cost of not
# recognising one is a reader seeing `openai_compatible`, which is what they
# see today. The cost of recognising one wrongly is worse.
_BY_HOST: tuple[tuple[str, str], ...] = (("openrouter.ai", "OpenRouter"),)


def label_for(type_: str, base_url: str | None = None, said: str | None = None) -> str | None:
    """A name a person would recognise this endpoint by, or None.

    `openai_compatible` is four products in a trench coat -- vLLM, SGLang, LM
    Studio, llama.cpp and every hosted router speak it -- so a panel that
    printed the type told a reader nothing about who they were talking to.

    Three sources, and the order is the whole point:

    1. **What the server said about itself** (`said`, from `owned_by` on its
       own listing). This is the only one that is evidence rather than
       inference, and it is what tells vLLM from SGLang -- they share a
       default port, so no amount of looking at the address ever could.
    2. **The address**, for the endpoints `CANDIDATES` already writes down for
       detection. Right for a server that names itself nothing.
    3. Nothing, and the caller falls back to the bare type.

    A name typed into the binding is deliberately **not** among them. That is
    what its author believed when they wrote it, and the entire reason to ask
    an endpoint anything is to find out what is really there.
    """
    if said:
        return said
    if type_ == "anthropic":
        return "Claude API"
    if type_ == "ollama":
        return "Ollama"
    if not base_url:
        return None
    lowered = base_url.lower()
    for host, name in _BY_HOST:
        if host in lowered:
            return name
    for candidate in CANDIDATES:
        if candidate.base_url and candidate.base_url.lower() == lowered:
            return candidate.label
    return None


def lists_installed(type_: str) -> bool:
    """Whether this backend lists what is **on this machine** rather than what
    it offers.

    Two listings that look identical and mean different things. Ollama's
    `/api/tags` is `ollama list`: models pulled onto this disk, ready now, and
    all of them. OpenRouter's is a catalogue of what it would route to for
    money, with nothing here yet. A panel that drew both the same way would
    have a reader believe they had four hundred models sitting on a laptop.
    """
    return type_ == "ollama"


async def probe() -> list[Engine]:
    """Every engine that answers, asked all at once, in CANDIDATES order.

    An engine serving nothing is left out: naming it would write a binding
    that fails on the project's first run.
    """

    async def one(candidate: Candidate) -> Engine | None:
        models = await models_for(candidate.type, candidate.base_url)
        if not models:
            return None
        return Engine(
            key=candidate.key,
            label=candidate.label,
            type=candidate.type,
            models=models,
            base_url=candidate.base_url,
        )

    found = await asyncio.gather(*(one(c) for c in CANDIDATES))
    return [engine for engine in found if engine is not None]


def detect() -> list[Engine]:
    """:func:`probe` for a caller that is not already in an event loop."""
    return asyncio.run(probe())
