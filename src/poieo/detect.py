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
    """An address detection knows how to ask, and how to read the answer."""

    key: str
    label: str
    type: str
    # None means "not an address": asked through its own SDK instead.
    base_url: str | None = None
    path: str = ""
    # The key holding the list, and the key on each entry holding its id.
    listing: str = ""
    field: str = ""


# Everything detection knows how to look for, in the order a picker shows them
# -- which is also the order an unattended `init` takes its answer from. Claude
# leads because that is the order this has always resolved in: a key on the
# machine is a decision somebody already made.
CANDIDATES: tuple[Candidate, ...] = (
    Candidate("claude", "Claude API", "anthropic"),
    Candidate(
        "ollama", "Ollama", "ollama",
        "http://localhost:11434", "/api/tags", "models", "name",
    ),
    Candidate(
        "lmstudio", "LM Studio", "openai_compatible",
        "http://localhost:1234/v1", "/models", "data", "id",
    ),
    Candidate(
        "vllm", "vLLM / SGLang", "openai_compatible",
        "http://localhost:8000/v1", "/models", "data", "id",
    ),
    Candidate(
        "llamacpp", "llama.cpp", "openai_compatible",
        "http://localhost:8080/v1", "/models", "data", "id",
    ),
)


async def _listed(candidate: Candidate) -> Engine | None:
    """Ask one HTTP address what it has.

    Every outcome is a return value, never an exception -- including a 200
    that is not JSON, which is what a proxy or a captive portal answers with.
    An engine with nothing installed is not offered either: naming it would
    write a binding that fails on the project's first run.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(f"{candidate.base_url}{candidate.path}")
    except httpx.RequestError:
        return None
    if response.status_code >= 400:
        return None
    try:
        listed = response.json().get(candidate.listing)
    except ValueError:
        return None
    if not isinstance(listed, list):
        return None

    # In the server's own order, which is the order the user already knows
    # from `ollama list`.
    names = tuple(
        str(entry[candidate.field])
        for entry in listed
        if isinstance(entry, dict) and entry.get(candidate.field)
    )[:MODEL_CAP]
    if not names:
        return None
    return Engine(
        key=candidate.key,
        label=candidate.label,
        type=candidate.type,
        models=names,
        base_url=candidate.base_url,
    )


async def _claude() -> Engine | None:
    """Claude, if this machine holds a credential the SDK will accept.

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
        names = tuple(str(model.id) for model in listed.data)
    except Exception:
        # Any refusal at all means "not available here". The user is about to
        # be shown a list; a stack trace is not one of the options on it.
        return None
    finally:
        if client is not None:
            await client.close()
    if not names:
        return None
    return Engine(
        key="claude", label="Claude API", type="anthropic", models=names
    )


async def probe() -> list[Engine]:
    """Every engine that answers, asked all at once, in CANDIDATES order."""

    async def one(candidate: Candidate) -> Engine | None:
        if candidate.base_url is None:
            return await _claude()
        return await _listed(candidate)

    found = await asyncio.gather(*(one(c) for c in CANDIDATES))
    return [engine for engine in found if engine is not None]


def detect() -> list[Engine]:
    """:func:`probe` for a caller that is not already in an event loop."""
    return asyncio.run(probe())
