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


def describe_invalid(exc: Exception, known_keys: "tuple[str, ...]" = ()) -> str:
    """A validation failure in the user's words, one line per problem.

    Pydantic's own rendering is written for developers -- type slugs, a docs
    URL -- and it is what a user with a typo in a YAML file used to see. Keys
    close to a real one get a suggestion, because 'promt' is a slip of the
    fingers, not a gap in understanding.
    """
    from difflib import get_close_matches

    errors = getattr(exc, "errors", None)
    if errors is None:
        return str(exc)

    lines = []
    for err in errors():
        key = ".".join(str(part) for part in err.get("loc", ()))
        kind = err.get("type", "")
        if kind == "extra_forbidden":
            line = f"'{key}' is not a setting here"
            close = get_close_matches(key, known_keys, n=1)
            if close:
                line += f" -- did you mean '{close[0]}'?"
        elif kind == "missing":
            line = f"'{key}' is required"
        else:
            line = f"'{key}': {err.get('msg', kind)}" if key else err.get("msg", kind)
        lines.append(line)
    return "; ".join(lines) or str(exc)
