"""A model drafts a task card from a conversation, for the board's form.

The new-task panel lets a person say the work in their own words. This module
is the half of that which does not touch the daemon: what the model is told
before the conversation, what a conversation may be, and how a card is read
out of the reply. The route in `server.py` supplies the project's folders and
tasks, chooses the model through the binding, and checks the card's folder
and schedule against the same fences the form's save would apply.

Nothing here writes a file. The card still lands on the form, and the form's
one save is still the only door a task comes through.

Design: docs/web.md
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from ..errors import SpecError

# The role the conversation is put to. It resolves through `default` when
# the models file does not name it, unlike the memory board's roles: a person
# typed the message and pressed the button, and the answer says which model
# replied, so nothing is chosen in silence.
ROLE = "task_writer"

TURNS_AT_MOST = 30
TURN_CHARS_AT_MOST = 4000

# The one block the model is asked to write when it proposes a card, and then
# any fence at all: smaller models answer with ```json or ```yaml whatever
# they were asked, and a block that holds a name and a prompt is a card
# whichever way it came. Prose is never one, because a card is a mapping
# with those two keys and a sentence does not parse to that.
_LABELLED = re.compile(r"```poieo-task[ \t]*\n(.*?)\n?```", re.DOTALL)
_ANY_FENCE = re.compile(r"```[\w-]*[ \t]*\n(.*?)\n?```", re.DOTALL)


def conversation(turns: Any) -> list[dict[str, str]]:
    """The turns a request carries, checked, or a SpecError saying what is wrong.

    Bounded twice: a turn's length and the number of turns, because the whole
    conversation is sent again with every message and a page could otherwise
    put an arbitrarily large request to a metered endpoint.
    """
    if not isinstance(turns, list) or not turns:
        raise SpecError("a conversation is a list of turns")
    if len(turns) > TURNS_AT_MOST:
        raise SpecError(f"a conversation is at most {TURNS_AT_MOST} turns; start a new one")
    kept: list[dict[str, str]] = []
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("role") not in {"user", "assistant"}:
            raise SpecError("a turn has a role, user or assistant, and its words")
        content = turn.get("content")
        if not isinstance(content, str) or not content.strip():
            raise SpecError("a turn has a role, user or assistant, and its words")
        if len(content) > TURN_CHARS_AT_MOST:
            raise SpecError(f"a turn is at most {TURN_CHARS_AT_MOST} characters")
        kept.append({"role": str(turn["role"]), "content": content})
    if kept[-1]["role"] != "user":
        raise SpecError("the last turn is the person's")
    return kept


def briefing(project: str, folders: list[dict[str, str]], tasks: list[tuple[str, str, str]]) -> str:
    """What the model is told before it reads the conversation.

    The folders are spelled as a card spells them, because that is what the
    form's folder field takes and what the fence on save will check. The
    tasks already on the board are named so the model does not propose one
    the project has. Neither is an instruction from the person; both are
    facts about the project the person is looking at.
    """
    offered = "\n".join(f"- {folder['path']} ({folder['name']})" for folder in folders) or "- (none listed)"
    running = "\n".join(f"- {task_id} ({title}): {schedule}" for title, task_id, schedule in tasks) or "- none yet"
    return (
        "You help a person write a task for poieo, which keeps tasks running on their own machine. "
        "A task is a card with four fields: name, a short title; folder, the one place the task's "
        "model may read and change files; prompt, the instructions the model follows on every run, "
        "with file and shell tools; and schedule. Runs are unattended: each starts from the prompt "
        "and the task's journal of earlier runs. In a Git folder the work happens in a private copy "
        "and file changes wait for the person's review.\n\n"
        f"Project: {project}\n"
        "Folders a card may name, spelled as a card spells them:\n"
        f"{offered}\n"
        "Tasks this project already runs:\n"
        f"{running}\n\n"
        "Answer in the language the person writes in, and briefly. If you cannot tell what the work "
        "is, ask one question. Otherwise propose a card: a line or two of prose, then exactly one "
        "fenced block labelled poieo-task holding JSON with the keys name, folder, prompt and "
        "schedule, exactly like this:\n\n"
        "```poieo-task\n"
        '{"name": "nightly test fix", "folder": "../src", '
        '"prompt": "Run the test suite. If a test fails, fix one failure and run it again.", '
        '"schedule": "0 2 * * *"}\n'
        "```\n\n"
        "Use a folder from the list, spelled as the list spells it, and only when the person's "
        'words point to it; otherwise leave folder as "" and say that they choose it on the form. '
        "Write the prompt as instructions to a capable agent working alone: what to do, how to "
        'check it, and what to leave alone. Schedule is "" for hourly, an interval such as 30m or '
        "2h, the word loop, or five cron fields such as 0 2 * * *. Do not describe this format to "
        "the person."
    )


def _card_in(text: str) -> dict[str, Any] | None:
    """A mapping with a name and a prompt, if that is what this text is."""
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if isinstance(parsed, dict) and parsed.get("name") and parsed.get("prompt"):
        return parsed
    return None


def read_card(text: str) -> tuple[str, dict[str, Any] | None]:
    """The prose without its card, and the card if the reply carried one.

    JSON is what the model is asked for, and JSON is YAML, so one reader takes
    a card written either way. The labelled fence is looked for first, then
    any fence, then the whole reply -- a local model asked in Korean wrote the
    four lines bare, and a person who got them as prose would have had to
    copy each into its field. A fence that could not be read stays in the
    prose: the person then sees what the model wrote rather than nothing.
    """
    for pattern in (_LABELLED, _ANY_FENCE):
        for match in pattern.finditer(text):
            card = _card_in(match.group(1))
            if card is not None:
                return (text[: match.start()] + text[match.end() :]).strip(), card
    card = _card_in(text)
    if card is not None:
        return "", card
    return text.strip(), None
