"""The physical layer: which model actually executes each logical role.

A binding file declares endpoints (``providers``) and then maps roles onto them.
Swapping a workflow from local inference to the Claude API is a one-file edit
that never touches the graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import BindingError, SpecError, describe_invalid
from .graph import load_document

# Populated by `poieo.providers.register()` at import time. Keeping the set here
# rather than a closed Literal lets a caller add a backend without editing this
# module, while still rejecting typos when the binding is parsed.
KNOWN_PROVIDER_TYPES: set[str] = set()


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderSpec(_Spec):
    """One physical endpoint that can serve completions."""

    type: str
    base_url: str | None = None
    # Read the credential from the environment; never store keys in the file.
    api_key_env: str | None = None
    timeout: float = Field(default=600.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    # Provider-specific extras (e.g. mock scripts, anthropic betas).
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if KNOWN_PROVIDER_TYPES and value not in KNOWN_PROVIDER_TYPES:
            raise ValueError(
                f"unknown provider type '{value}'; "
                f"known types: {sorted(KNOWN_PROVIDER_TYPES)}"
            )
        return value

    @model_validator(mode="after")
    def _check_endpoint(self) -> ProviderSpec:
        if self.type in {"openai_compatible", "ollama"} and not self.base_url:
            raise ValueError(f"provider type '{self.type}' requires a base_url")
        return self


class ModelSpec(_Spec):
    """A role's target: an endpoint, a model id, and generation parameters."""

    provider: str | None = None
    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    def merged_with(self, base: ModelSpec) -> ModelSpec:
        """Layer this spec over ``base``; params merge key-by-key."""
        return ModelSpec(
            provider=self.provider or base.provider,
            model=self.model or base.model,
            params={**base.params, **self.params},
        )


class BindingSpec(_Spec):
    name: str = "default"
    version: int = 1
    providers: dict[str, ProviderSpec] = Field(default_factory=dict)
    # Applied to every role that does not override it.
    default: ModelSpec = Field(default_factory=ModelSpec)
    roles: dict[str, ModelSpec] = Field(default_factory=dict)

    source_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _check_providers(self) -> BindingSpec:
        if not self.providers:
            raise ValueError("a binding must declare at least one provider")
        named = [("default", self.default), *self.roles.items()]
        for role, spec in named:
            if spec.provider and spec.provider not in self.providers:
                raise ValueError(
                    f"role '{role}' points at undeclared provider '{spec.provider}'"
                )
        return self

    def resolve(self, role: str, overrides: dict[str, Any] | None = None) -> ResolvedModel:
        """Turn a logical role into a concrete provider + model + params."""
        spec = self.roles.get(role, ModelSpec()).merged_with(self.default)
        if overrides:
            spec = ModelSpec(params=overrides).merged_with(spec)
        if not spec.provider:
            raise BindingError(
                f"role '{role}' has no provider, and the binding declares no default"
            )
        if not spec.model:
            raise BindingError(
                f"role '{role}' has no model id, and the binding declares no default"
            )
        return ResolvedModel(
            role=role,
            provider_name=spec.provider,
            provider=self.providers[spec.provider],
            model=spec.model,
            params=spec.params,
        )

    def undeclared(self, roles: set[str]) -> list[str]:
        """Which of these roles this binding never names.

        Not the same question as :meth:`check_roles`, and the one that catches
        a typo. ``resolve`` falls back to ``default`` for *any* role, which is
        the point of having a default -- a mock binding that declares no roles
        at all is a legitimate way to run a graph. It is also why nothing has
        ever reported `role: classifer`, which quietly gets the default model
        instead of the cheap one the node asked for.

        So this is a question, not a verdict. The caller decides whether an
        answer is worth saying out loud.
        """
        return sorted(role for role in roles if role not in self.roles)

    def check_roles(self, roles: set[str]) -> list[str]:
        """Which of these roles this binding cannot resolve at all.

        Which is fewer than a reader expects: an unknown role resolves through
        ``default``, so this only answers for a binding that declares neither
        a provider nor a model to fall back on. :meth:`undeclared` is the
        question about a role the binding never heard of.
        """
        missing = []
        for role in sorted(roles):
            try:
                self.resolve(role)
            except BindingError:
                missing.append(role)
        return missing


class ResolvedModel(_Spec):
    """What a node is actually going to call."""

    role: str
    provider_name: str
    provider: ProviderSpec
    model: str
    params: dict[str, Any] = Field(default_factory=dict)

    def describe(self) -> str:
        return f"{self.role} -> {self.provider_name}:{self.model}"


def load_binding(path: str | Path) -> BindingSpec:
    path = Path(path)
    data = load_document(path)
    try:
        binding = BindingSpec.model_validate(data)
    except Exception as exc:
        raise SpecError(
            f"{path}: invalid binding: "
            f"{describe_invalid(exc, tuple(BindingSpec.model_fields))}"
        ) from exc
    binding.source_path = path
    return binding
