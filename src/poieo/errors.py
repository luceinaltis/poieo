"""Exception hierarchy for the poieo harness."""

from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True)
class Cause:
    """A failure in the user's words: what happened, and one thing to try.

    ``slug`` is the stable key -- the pause logic counts by it and the web
    groups by it; the sentences may be reworded freely, the slug may not.
    """

    slug: str
    said: str
    fix: str

    def as_dict(self) -> dict[str, str]:
        return {"slug": self.slug, "said": self.said, "fix": self.fix}


def explain_failure(exc: BaseException) -> Cause | None:
    """The user-level cause of a failure, or None when honesty demands it.

    Walks the exception chain, so a ProviderError wrapped in a NodeError
    still explains itself. Matching is on types first and message shapes
    second; an unmatched failure returns None -- an honest "unclassified"
    beats a wrong sentence, and the raw error is always still there.
    """
    seen: set[int] = set()
    err: BaseException | None = exc
    while err is not None and id(err) not in seen:
        seen.add(id(err))
        message = str(err)

        if isinstance(err, ProviderError):
            if "is not set" in message or "authentication" in message.lower():
                return Cause(
                    "no_credentials",
                    "the model's credentials are missing",
                    "set the key the error names, then `poieo check`",
                )
            if "HTTP 4" in message and not err.retryable:
                return Cause(
                    "rejected",
                    "the model rejected the request",
                    "check the model name and params in the binding",
                )
            # Overload (429/5xx) lands here too: the server's mood, not the
            # request's shape, so the unreachable advice is the right one.
            if err.retryable or "cannot reach" in message or "connection error" in message:
                return Cause(
                    "unreachable",
                    "the model could not be reached",
                    "is the server running? `poieo check` probes every provider",
                )
        elif isinstance(err, IsolationError):
            return Cause(
                "no_isolation",
                "the isolated environment could not be provided",
                "is docker running? `poieo reset <task>` rebuilds the environment",
            )
        elif isinstance(err, ExpressionError):
            return Cause(
                "bad_expression",
                "an expression in the graph failed at run time",
                "`poieo validate` catches most of these before a run",
            )
        elif isinstance(err, RunAborted):
            if "max_steps" in message:
                return Cause(
                    "cycling",
                    "the graph kept cycling and hit max_steps",
                    "add an exit condition, or raise max_steps",
                )
        elif isinstance(err, NodeError):
            if "hit max_turns" in message:
                return Cause(
                    "out_of_turns",
                    "ran out of turns before finishing",
                    "raise max_turns, or make the step smaller",
                )
            if "was cut off before it finished" in message:
                return Cause(
                    "out_of_room",
                    "the model was cut off before it finished",
                    "raise max_tokens for this node or its role -- a model that "
                    "reasons spends that budget on thinking too",
                )
            if "expected JSON output" in message or "output path" in message:
                return Cause(
                    "bad_output",
                    "the answer was not the shape the graph expects",
                    "loosen output.format, or show the model an example in the prompt",
                )
            if "workdir does not exist" in message:
                return Cause(
                    "folder_gone",
                    "the folder it works in is missing",
                    "restore the folder, or point the card somewhere that exists",
                )
        err = err.__cause__
    return None


def describe_invalid(exc: Exception, known_keys: "tuple[str, ...]" = ()) -> str:
    """A validation failure in the user's words, one line per problem.

    Pydantic's own rendering is written for developers. Keys close to a real
    one get a suggestion: 'promt' is a slip of the fingers, not a gap in
    understanding.
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
            # Matched on the last segment, so a typo nested inside a list --
            # `nodes.0.promt` in a graph file -- gets the same help it would
            # get at the top level. The reader is told the full path and
            # asked about the word they actually mistyped.
            close = get_close_matches(key.rsplit(".", 1)[-1], known_keys, n=1)
            if close:
                line += f" -- did you mean '{close[0]}'?"
        elif kind == "missing":
            line = f"'{key}' is required"
        else:
            line = f"'{key}': {err.get('msg', kind)}" if key else err.get("msg", kind)
        lines.append(line)
    return "; ".join(lines) or str(exc)
