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

import httpx

# Per address, with all of them asked at once: init has to feel instant on a
# machine with nothing listening, and that is the common case.
HTTP_TIMEOUT = 1.5

# Enough to fill a picker. A server offering hundreds is a catalogue, not a
# choice, and the binding file is where the full name gets typed anyway.
MODEL_CAP = 40


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

# How to ask an endpoint of each type what it serves: the path, the key holding
# the list, and the key on each entry holding its id. Keyed by **provider
# type**, not by address, because the question outlives detection -- a binding
# declares a type and a base_url, and `poieo config models` asks the same way
# from there. Two copies of this would eventually look in two places.
_READERS: dict[str, tuple[str, str, str]] = {
    "ollama": ("/api/tags", "models", "name"),
    "openai_compatible": ("/models", "data", "id"),
}


async def _listed(base_url: str, reader: tuple[str, str, str]) -> tuple[str, ...]:
    """Ask one HTTP address what it has.

    Every outcome is a return value, never an exception -- including a 200
    that is not JSON, which is what a proxy or a captive portal answers with.
    """
    path, listing, field = reader
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(f"{base_url}{path}")
    except httpx.RequestError:
        return ()
    if response.status_code >= 400:
        return ()
    try:
        listed = response.json().get(listing)
    except ValueError:
        return ()
    if not isinstance(listed, list):
        return ()

    # In the server's own order, which is the order the user already knows
    # from `ollama list`.
    return tuple(
        str(entry[field])
        for entry in listed
        if isinstance(entry, dict) and entry.get(field)
    )[:MODEL_CAP]


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


async def models_for(type_: str, base_url: str | None = None) -> tuple[str, ...]:
    """What an endpoint of this type, at this address, serves **right now**.

    Empty when it cannot be reached, answers in a shape its type does not
    promise, or serves nothing at all. The one place that knows how each
    backend lists what it has, so detection and `poieo config models` can
    never disagree about where to look.
    """
    if type_ == "anthropic":
        return await _claude_models()
    reader = _READERS.get(type_)
    if reader is None or base_url is None:
        # A type with nothing to ask -- `mock` answers from its own file, and
        # an unknown backend registered by a caller has no listing convention.
        return ()
    return await _listed(base_url, reader)


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
