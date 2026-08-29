"""The provider contract every physical backend implements."""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass, field
from typing import Any

from ..binding import ProviderSpec
from ..errors import ProviderError


def credential_for(name: str, spec: ProviderSpec) -> str | None:
    """The key this provider needs from the environment, or None when it names
    no variable and lets its own SDK resolve one.

    One place, so that reading the rule costs nothing: no client is opened and
    no request is made, which is what lets the daemon check every credential
    before it arms a single task rather than discovering a missing key when a
    trigger fires at 3am.
    """
    if not spec.api_key_env:
        return None
    key = os.environ.get(spec.api_key_env)
    if not key:
        raise ProviderError(
            f"provider '{name}': ${spec.api_key_env} is not set", provider=name
        )
    return key


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def merge(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


@dataclass(slots=True)
class ToolDef:
    """A tool offered to the model, declared as JSON Schema."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    """One tool invocation the model asked for."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMRequest:
    """A provider-neutral completion request built by a model node."""

    model: str
    messages: list[dict[str, Any]]
    system: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    # The logical role this call came from -- carried for logging and mocks,
    # never sent to a backend.
    role: str | None = None
    # Tools offered for this call; empty means a plain completion.
    tools: list[ToolDef] = field(default_factory=list)


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None
    # Anything provider-specific worth keeping in the run log.
    meta: dict[str, Any] = field(default_factory=dict)
    # Calls the model wants executed; empty means it is done.
    tool_calls: list[ToolCall] = field(default_factory=list)


class Provider(abc.ABC):
    """A physical endpoint. One instance per declared provider, reused per run."""

    type: str = "base"

    def __init__(self, name: str, spec: ProviderSpec):
        self.name = name
        self.spec = spec

    @abc.abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Run one completion. Raise ProviderError on failure."""

    async def health(self) -> tuple[bool, str]:
        """Cheap reachability probe used by ``poieo providers check``."""
        return True, "no health check implemented"

    async def context_for(self, model: str) -> int | None:
        """How many tokens this model can hold, if the endpoint will say.

        The binding is the first answer and this is the second, for anyone who
        has not written the number down. Getting it wrong is not cheap: a
        hardcoded cap was 2.3% of what `z-ai/glm-5.3-flash` holds, and a step
        was watched re-reading one file eight times because of it.

        `None` for an endpoint that does not publish it, and **`None` for one
        that would not answer** -- asking is an optimisation and a run must
        never die because it failed. Implementations cache: this cannot become
        a round trip per turn.
        """
        return None

    async def aclose(self) -> None:
        """Release sockets/clients. Always called on daemon shutdown."""
