"""The provider contract every physical backend implements."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from ..binding import ProviderSpec, ResolvedModel


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
    """A provider-neutral completion request built by an llm node."""

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

    async def aclose(self) -> None:
        """Release sockets/clients. Always called on daemon shutdown."""

    def build_request(self, resolved: ResolvedModel, messages, system) -> LLMRequest:
        return LLMRequest(
            model=resolved.model,
            messages=messages,
            system=system,
            params=dict(resolved.params),
            role=resolved.role,
        )
