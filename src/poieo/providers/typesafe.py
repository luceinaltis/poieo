"""TypeSafe's System One API: a state and typed questions in, decisions out.

Jev writes nothing. Where every other backend here is asked for text, this one
is asked to *decide*: it is shown a state and a set of typed questions -- a
yes/no, a choice among named options, a score on a rubric -- and answers each
with its pick and the probabilities behind it, in one round trip.

It sits behind an ordinary agent node all the same, so a graph keeps naming
roles and nothing else. The node's rendered prompt is the state; what to
decide travels in ``params.questions``, the one place a node already carries
per-model settings; and the answers come back as the node's text, as JSON, for
``output: {format: json, path: ...}`` and a router to read the way they read
any other model's answer.

Design: docs/binding.md
"""

from __future__ import annotations

import json
from typing import Any

from ..errors import ProviderError
from .base import LLMRequest, LLMResponse, Usage
from .local import _HttpProvider
from .presets import Preset

# The documented flagship alias. Used only where no binding has named a model,
# which is the health probe.
_FLAGSHIP = "jev-latest"


def _state(name: str, request: LLMRequest) -> str:
    """Everything the model would be shown, as the one text it evaluates.

    A card always writes a system block, and a text model reads it as part of
    its prompt, so it is part of the state here too. A history is refused
    rather than flattened: it means a tool loop or a chat, and this model
    holds one state and answers once.
    """
    parts: list[str] = []
    if request.system:
        parts.append(request.system)
    for message in request.messages:
        if message.get("role") != "user":
            raise ProviderError(
                f"{name}: Jev decides on one state and cannot hold a conversation; "
                "this node carries a history, so it cannot be bound to a model that only decides",
                provider=name,
            )
        content = message.get("content")
        if content is None or content == "":
            continue
        parts.append(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
    return "\n\n".join(parts)


class TypeSafeProvider(_HttpProvider):
    """``POST /v1/systemone``: ``{model, state, questions}`` in, ``{answers}`` out."""

    type = "typesafe"
    address = Preset("https://api.typesafe.ai", "TYPESAFE_API_KEY")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if request.tools or request.hands is not None:
            raise ProviderError(
                f"{self.name}: Jev makes decisions and cannot run tools; give this node no `tools`",
                provider=self.name,
            )
        params = dict(request.params)
        questions = params.pop("questions", None)
        if not isinstance(questions, dict) or not questions:
            raise ProviderError(
                f"{self.name}: a node bound to Jev must say what to decide -- put its typed `questions` in `params`",
                provider=self.name,
            )

        state = _state(self.name, request)
        if not state:
            raise ProviderError(
                f"{self.name}: this node rendered nothing to decide on -- an empty prompt and no system block",
                provider=self.name,
            )

        data = await self._post("/v1/systemone", {"model": request.model, "state": state, "questions": questions})
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, dict):
            raise ProviderError(f"{self.name}: response contained no answers", provider=self.name)

        meta: dict[str, Any] = {}
        if params:
            # Generation settings inherited from the binding's `default` --
            # max_tokens, temperature, a thinking budget -- describe writing,
            # and this model writes nothing, so each holds trivially rather
            # than being dropped. The API documents exactly three request
            # fields, so nothing else is sent; the run record says which
            # settings were not.
            meta["ignored_params"] = sorted(params)
        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        return LLMResponse(
            text=json.dumps(answers, ensure_ascii=False),
            model=data.get("model") or request.model,
            usage=Usage(
                input_tokens=usage.get("input_tokens", 0) or 0,
                output_tokens=usage.get("output_tokens", 0) or 0,
            ),
            meta=meta,
        )

    async def health(self) -> tuple[bool, str]:
        """One question about two words.

        There is no `/models` to list here, so the only thing that can be
        asked is a decision: a few tokens at the published price, in exchange
        for knowing the key is good and the service is up.
        """
        try:
            data = await self._post(
                "/v1/systemone",
                {
                    "model": _FLAGSHIP,
                    "state": "poieo check",
                    "questions": {"reachable": {"type": "noul", "instructions": "Is this a health check?"}},
                },
            )
        except ProviderError as exc:
            return False, str(exc).removeprefix(f"{self.name}: ")
        if not isinstance(data, dict):
            return False, "reachable, but the answer was not the API's shape"
        return True, f"reachable ({data.get('model') or _FLAGSHIP})"
