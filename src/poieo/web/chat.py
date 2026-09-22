"""A conversation with the project's model, from the board.

The board's chat panel puts a person's messages to the model the project's
`default` role names and shows what it answers. This module is the half of
that which does not touch the daemon: what a conversation may be, and what
the model is told before it. The route in `server.py` chooses the model
through the binding and reports which one answered.

What a conversation may be -- its turns, their roles and its bounds -- is the
draft panel's rule too, so `conversation` is the one in `draft.py`.

Nothing here is kept. The page holds the conversation and sends the whole of
it with every message; the daemon writes no record of it, so there is nothing
for the terminal to disagree with, and no run is started by it.

Design: docs/web.md
"""

from __future__ import annotations

from .draft import TURN_CHARS_AT_MOST, TURNS_AT_MOST, conversation

# The role the conversation is put to: the project's model, the one a plain
# card gets. Nothing is chosen in silence -- the person typed the message and
# pressed send, and the reply says which model answered.
ROLE = "default"

# What the built-in providers say when the model stopped because it ran out of
# room rather than because it was done: OpenAI-shaped endpoints and Ollama say
# `length`, Anthropic says `max_tokens`. A thinking model can spend the whole
# budget thinking and answer with nothing, and an empty reply that says why is
# the difference between "raise max_tokens" and "the chat is broken".
CUT_SHORT = frozenset({"length", "max_tokens"})


def cut_short(stop_reason: str | None) -> bool:
    """Whether a reply stopped at the model's token limit rather than at its end."""
    return stop_reason in CUT_SHORT


def briefing(project: str) -> str:
    """What the model is told before it reads the conversation.

    Only what is true of where it is being asked from: which project's board
    this is, and that a chat is not a task -- it has no tools, so it can
    neither read the project nor change a file, and saying so keeps the model
    from claiming otherwise.
    """
    return (
        f"You are talking with a person on the poieo board for the project '{project}'. "
        "poieo keeps tasks running on their machine with the models they chose. This "
        "conversation is not a task: you have no tools here, cannot read or change files, "
        "and nothing said here is kept or run. Answer in the language the person writes in."
    )


__all__ = ["ROLE", "TURN_CHARS_AT_MOST", "TURNS_AT_MOST", "briefing", "conversation", "cut_short"]
