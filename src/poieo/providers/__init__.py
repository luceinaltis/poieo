"""Provider registry: binding spec in, live provider instance out."""

from __future__ import annotations

from ..binding import KNOWN_PROVIDER_TYPES, BindingSpec, ProviderSpec
from ..errors import ProviderError
from .anthropic_provider import AnthropicProvider
from .base import LLMRequest, LLMResponse, Provider, Usage, credential_for
from .local import OllamaProvider, OpenAICompatibleProvider
from .mock import MockProvider
from .presets import PRESETS
from .subscription import ClaudeCodeProvider, CodexProvider

_REGISTRY: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "ollama": OllamaProvider,
    "mock": MockProvider,
    # The two that spend a plan rather than a key. Named after the harness they
    # drive, because that is what a person logs into and what a failure names.
    "claude_code": ClaudeCodeProvider,
    "codex": CodexProvider,
}

# Every preset is the OpenAI wire format with its address filled in, so each
# name is a type in its own right -- which is what makes a typo in one a parse
# error rather than a connection failure at three in the morning.
_REGISTRY.update({name: OpenAICompatibleProvider for name in PRESETS})


def _addressed(spec: ProviderSpec) -> ProviderSpec:
    """Fill in what a preset knows and the binding did not say.

    Filled rather than forced: somebody who wrote a `base_url` meant it -- a
    proxy, a mirror, a gateway in front of the real thing -- and the same for a
    key variable. A preset is a starting point, not a cage.
    """
    preset = PRESETS.get(spec.type)
    if preset is None:
        return spec
    return spec.model_copy(
        update={
            "base_url": spec.base_url or preset.base_url,
            "api_key_env": spec.api_key_env or preset.api_key_env,
        }
    )


def register(type_name: str, cls: type[Provider]) -> None:
    """Add a backend; binding files may name it from that point on."""
    _REGISTRY[type_name] = cls
    KNOWN_PROVIDER_TYPES.add(type_name)


KNOWN_PROVIDER_TYPES.update(_REGISTRY)


def build_provider(name: str, spec: ProviderSpec) -> Provider:
    spec = _addressed(spec)
    cls = _REGISTRY.get(spec.type)
    if cls is None:
        raise ProviderError(f"unknown provider type '{spec.type}'", provider=name)
    return cls(name, spec)


def check_credentials(binding: BindingSpec, roles: set[str]) -> None:
    """Every credential the given roles will ask for, before anything is armed.

    Reads the environment and opens nothing, so this is a load-time check
    rather than a probe: `poieo check` is the one that talks to a server.

    Only the roles a graph actually names -- a spare endpoint declared in the
    binding but bound to nothing is not going to be called, and holding the
    daemon down for its key would make the binding file harder to keep than
    the tasks it serves.
    """
    checked: set[str] = set()
    for role in sorted(roles):
        resolved = binding.resolve(role)
        if resolved.provider_name in checked:
            continue
        checked.add(resolved.provider_name)
        credential_for(resolved.provider_name, resolved.provider)


class ProviderPool:
    """Lazily instantiates providers and keeps one instance per name.

    Provider construction opens HTTP clients, so a long-lived daemon builds each
    endpoint once and closes them all on shutdown.
    """

    def __init__(self, binding: BindingSpec):
        self.binding = binding
        self._instances: dict[str, Provider] = {}

    def get(self, name: str) -> Provider:
        if name not in self._instances:
            spec = self.binding.providers.get(name)
            if spec is None:
                raise ProviderError(f"provider '{name}' is not declared in the binding")
            self._instances[name] = build_provider(name, spec)
        return self._instances[name]

    def instantiated(self) -> dict[str, Provider]:
        return dict(self._instances)

    async def aclose(self) -> None:
        for provider in self._instances.values():
            await provider.aclose()
        self._instances.clear()

    async def __aenter__(self) -> ProviderPool:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


__all__ = [
    "LLMRequest",
    "LLMResponse",
    "Provider",
    "ProviderPool",
    "Usage",
    "build_provider",
    "check_credentials",
    "credential_for",
    "register",
]
