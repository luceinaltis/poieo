"""Exception hierarchy for the poieo harness."""

from __future__ import annotations


class PoieoError(Exception):
    """Base class for every error raised by poieo."""


class SpecError(PoieoError):
    """A graph, binding, or daemon spec is malformed or inconsistent."""


class ExpressionError(PoieoError):
    """An expression or prompt template failed to parse or evaluate."""


class BindingError(PoieoError):
    """A logical role could not be resolved to a physical model."""


class ProviderError(PoieoError):
    """A model provider failed to produce a completion."""

    def __init__(self, message: str, *, provider: str = "", retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class IsolationError(PoieoError):
    """An isolated environment could not be provided. Never fall back without one."""


class NodeError(PoieoError):
    """A node failed during execution."""

    def __init__(self, message: str, *, node_id: str = ""):
        super().__init__(message)
        self.node_id = node_id


class RunAborted(PoieoError):
    """A run was stopped before reaching a terminal node."""
