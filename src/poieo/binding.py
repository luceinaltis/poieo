"""The physical layer: which model actually executes each logical role.

A binding file declares endpoints (``providers``) and then maps roles onto them.
Swapping a workflow from local inference to the Claude API is a one-file edit
that never touches the graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import BindingError
from .graph import load_spec

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
    # Headers to send with every request, laid over the ones built from
    # `api_key_env`. For an endpoint that speaks the OpenAI shape and none of
    # its plumbing: Azure wants the key in `api-key` rather than in an
    # `Authorization: Bearer`, and without this the largest OpenAI-shaped
    # endpoint there is could not be reached by the provider named after that
    # shape. **Values are literal, so a key does not belong here** -- put it in
    # the environment and name the variable in `api_key_env`, which is the rule
    # the rest of this file exists to keep.
    headers: dict[str, str] = Field(default_factory=dict)
    # Query parameters on every request. Azure's `api-version` is required and
    # is not part of any path, so a base URL cannot carry it.
    query: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(default=600.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    # Provider-specific extras (e.g. mock scripts, anthropic betas).
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if KNOWN_PROVIDER_TYPES and value not in KNOWN_PROVIDER_TYPES:
            raise ValueError(f"unknown provider type '{value}'; known types: {sorted(KNOWN_PROVIDER_TYPES)}")
        return value

    @model_validator(mode="after")
    def _check_endpoint(self) -> ProviderSpec:
        if self.type in {"openai_compatible", "ollama"} and not self.base_url:
            raise ValueError(f"provider type '{self.type}' requires a base_url")
        return self


class Prices(_Spec):
    """What an endpoint charges, per million tokens.

    Per million because that is the unit every vendor quotes in, so the number
    in a binding is the number on the pricing page -- not one somebody
    converted by hand and got wrong by six zeroes.

    Only for endpoints that bill and do not say so. OpenRouter reports `cost`
    on the response when asked and needs none of this; Anthropic's API carries
    no cost at all, and it is the paid backend these examples ship for.

    Every field defaults to zero rather than being required, because a binding
    that names only what it is charged for reads better than one padded with
    zeroes -- and a rate nobody wrote is a rate nobody is paying.
    """

    input: float = Field(default=0.0, ge=0)
    output: float = Field(default=0.0, ge=0)
    cache_read: float = Field(default=0.0, ge=0)
    cache_write: float = Field(default=0.0, ge=0)

    def charge(self, usage: Any) -> float:
        """What this usage comes to, in whatever currency the rates are in.

        Cached input is charged at the cache rate and **not** also at the input
        one: `input_tokens` is the whole prompt and `cache_read_tokens` is the
        part of it that was already there, so counting both would bill the
        cached half twice.
        """
        fresh = max(0, usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens)
        return (
            fresh * self.input
            + usage.cache_read_tokens * self.cache_read
            + usage.cache_write_tokens * self.cache_write
            + usage.output_tokens * self.output
        ) / 1_000_000


class ModelSpec(_Spec):
    """A role's target: an endpoint, a model id, and generation parameters."""

    provider: str | None = None
    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    # How much this model can hold, in tokens.
    #
    # Beside `model` rather than inside `params`, because it describes the
    # endpoint rather than asking it for anything: put in `params` it would be
    # posted in the request body, where a strict API rejects what it does not
    # recognise.
    #
    # `None` means "nobody has said", which is a different fact from any
    # number and is left for the caller to answer however it can. A default
    # here would be a guess wearing a measurement's clothes -- the models this
    # project binds differ by a factor of five (262,144 tokens for a local
    # qwen3.5, 1,310,720 for z-ai/glm-5.3-flash), so any single number is
    # wrong for most of them.
    context: int | None = Field(default=None, gt=0)
    # What this endpoint charges, for one that bills without saying so. Beside
    # `model` for the same reason `context` is: it describes the endpoint
    # rather than asking it for anything, and in `params` it would be posted in
    # the request body.
    prices: Prices | None = None

    def merged_with(self, base: ModelSpec) -> ModelSpec:
        """Layer this spec over ``base``; params merge key-by-key."""
        return ModelSpec(
            provider=self.provider or base.provider,
            model=self.model or base.model,
            params={**base.params, **self.params},
            context=self.context or base.context,
            prices=self.prices or base.prices,
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
                raise ValueError(f"role '{role}' points at undeclared provider '{spec.provider}'")
        return self

    def resolve(self, role: str, overrides: dict[str, Any] | None = None) -> ResolvedModel:
        """Turn a logical role into a concrete provider + model + params."""
        spec = self.roles.get(role, ModelSpec()).merged_with(self.default)
        if overrides:
            spec = ModelSpec(params=overrides).merged_with(spec)
        if not spec.provider:
            raise BindingError(f"role '{role}' has no provider, and the binding declares no default")
        if not spec.model:
            raise BindingError(f"role '{role}' has no model id, and the binding declares no default")
        return ResolvedModel(
            role=role,
            provider_name=spec.provider,
            provider=self.providers[spec.provider],
            model=spec.model,
            params=spec.params,
            context=spec.context,
            prices=spec.prices,
        )

    def undeclared(self, roles: set[str]) -> list[str]:
        """Which of these roles this binding never names.

        The question that catches a typo: ``resolve`` falls back to ``default``
        for *any* role, so `role: classifer` quietly gets the default model
        instead of the cheap one the node asked for.

        A question, not a verdict -- the caller decides whether an answer is
        worth saying out loud. See :meth:`check_roles` for the other one.
        """
        return sorted(role for role in roles if role not in self.roles)

    def check_roles(self, roles: set[str]) -> list[str]:
        """Which of these roles this binding cannot resolve at all.

        Fewer than a reader expects: an unknown role resolves through
        ``default``, so this only answers for a binding that declares neither
        a provider nor a model to fall back on.
        """
        missing = []
        for role in sorted(roles):
            try:
                self.resolve(role)
            except BindingError:
                missing.append(role)
        return missing

    def target(self, role: str) -> str | None:
        """``provider/model`` for a role, or None when this cannot say.

        The form `poieo config use` takes back, so a reader who types what
        they just read is right. Only a binding with nothing to fall back on
        gets None -- reporting what would really run beats refusing to report,
        which is the same call the board makes and for the same reason.
        """
        try:
            return self.resolve(role).ref
        except BindingError:
            return None

    def spoken_for(self) -> dict[str, str]:
        """Which ``provider/model`` each named role -- and ``default`` -- points
        at, leaving out any this binding cannot answer for."""
        named = {"default": self.target("default")}
        named.update({role: self.target(role) for role in self.roles})
        return {role: target for role, target in named.items() if target}

    def roles_by_target(self) -> dict[str, list[str]]:
        """`spoken_for` read the other way: every role each model answers for.

        A list, because the mapping is many-to-one -- pointing `classifier` and
        `writer` at one small model is the ordinary reason to name roles at
        all. The two listings inverted it themselves and disagreed about that:
        the board gathered a list, and the terminal's dict comprehension kept
        whichever role came last and dropped the rest without saying. It is one
        function now, so a reader gets the same answer whichever they asked.
        """
        found: dict[str, list[str]] = {}
        for role, target in self.spoken_for().items():
            found.setdefault(target, []).append(role)
        return found


class ResolvedModel(_Spec):
    """What a node is actually going to call."""

    role: str
    provider_name: str
    provider: ProviderSpec
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    # Tokens this model can hold, if the binding said. See `ModelSpec.context`.
    context: int | None = None
    # What it charges, if the binding said. See `ModelSpec.prices`.
    prices: Prices | None = None

    @property
    def ref(self) -> str:
        """``provider/model``: how a model is named everywhere a person reads
        or types one.

        Slash-separated because this is the form ``poieo config use`` takes
        back, and a reader who types what they just read has to be right. It
        splits once, so an id full of slashes (``hf.co/empero-ai/...``)
        survives whole. Four places used to spell this themselves, and one of
        them with a colon.
        """
        return f"{self.provider_name}/{self.model}"

    def describe(self) -> str:
        return f"{self.role} -> {self.ref}"


def split_ref(target: str) -> tuple[str, str]:
    """``provider/model`` read back into its two halves.

    The inverse of :attr:`ResolvedModel.ref`, and here beside it: one place
    builds the spelling and one place reads it, so a reader who types what
    they just read is right.

    **Split once.** A model id is full of slashes (``hf.co/empero-ai/...``)
    and a provider name never is.
    """
    provider, sep, model = target.partition("/")
    if not sep or not model or not provider:
        raise BindingError(
            f"'{target}' is not a provider/model reference. `poieo config` "
            f"prints them in exactly the form this takes back."
        )
    return provider, model


def load_binding(path: str | Path) -> BindingSpec:
    return load_spec(path, BindingSpec, "binding")
