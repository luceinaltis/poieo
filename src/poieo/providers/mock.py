"""A deterministic in-process provider for tests and dry runs.

Declare it in a binding to exercise a graph's wiring without spending tokens:

    providers:
      fake:
        type: mock
        options:
          responses:
            classifier: "bug"     # keyed by role, or "*" for a catch-all
"""

from __future__ import annotations

from typing import Any

from ..binding import ProviderSpec
from ..errors import ProviderError
from .base import LLMRequest, LLMResponse, Provider, Usage


class MockProvider(Provider):
    type = "mock"

    def __init__(self, name: str, spec: ProviderSpec):
        super().__init__(name, spec)
        options: dict[str, Any] = spec.options or {}
        self.responses: dict[str, Any] = options.get("responses", {})
        self.fallback: str = options.get("fallback", "")
        # Every request, in order -- assertions in tests read this.
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        key = request.role or request.model
        value = self.responses.get(key, self.responses.get("*", self.fallback))
        if isinstance(value, list):
            # A list is a script: one entry per call to this role.
            index = sum(1 for c in self.calls if (c.role or c.model) == key)
            if not value:
                raise ProviderError(f"mock '{self.name}': empty script", provider=self.name)
            value = value[min(index - 1, len(value) - 1)]
        text = value if isinstance(value, str) else str(value)
        return LLMResponse(
            text=text,
            model=request.model,
            usage=Usage(input_tokens=0, output_tokens=len(text.split())),
            stop_reason="end_turn",
        )

    async def health(self) -> tuple[bool, str]:
        return True, f"mock provider ({len(self.responses)} scripted role(s))"
