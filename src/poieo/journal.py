"""One journal per task: the append-only file every run, decision and note lands in.

One markdown file per task, appended to and never rewritten, so a line the
user types by hand works exactly like a line poieo wrote. The card reads it
into the prompt; the daemon, the CLI, the run records and the ``tell`` tool
write to it. It sits below all of them, so each can write a line without
loading the card.

Design: docs/tasks.md
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("poieo.journal")

# How many journal entries reach the prompt. The file keeps everything; this
# only bounds what the model is asked to hold in mind.
JOURNAL_LIMIT = 20
# A single entry is one line, so a chatty model cannot bury the rest.
JOURNAL_WIDTH = 300

# What a task writes at the end of its own run; the last such line is the
# bookmark. "nothing" is reserved: no writer produces it yet.
OWN_KINDS = ("did", "nothing")
# One entry looks like: `- <date> <time> {sep} <kind padded> <text>`.
PREFIX = "- "
SEPARATOR = " · "
NEW_HEADER = "New since you last worked:"
OLD_HEADER = "What you did before that:"


def closing_line(result: Any, fallback: str = "(said nothing)") -> str:
    """What the model said last, with the wording a journal line wants.

    The reading itself is `RunResult.said`, beside the `path` and `outputs` it
    walks. This is the default a reader of a journal should see when a run
    produced no text at all; the run summary carries the bare answer instead.
    """
    return result.said(fallback)


def _entries(path: Path) -> list[str]:
    """Every journal line, as text -- never parsed."""
    try:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, UnicodeDecodeError) as exc:
        # Forgetting beats failing, but say so: a task that cannot read its
        # journal repeats itself silently. A file saved in another encoding
        # is unreadable in the same way a missing permission is.
        log.warning("could not read the journal %s: %s", path, exc)
        raw = ""
    return [line.rstrip() for line in raw.splitlines() if line.strip() and not line.startswith("#")]


def _is_own_entry(line: str) -> bool:
    """Is this line the task writing about its own run?

    Read by structure, not by searching the text: a forged bookmark would mark
    real notes as read, silently.
    """
    head, sep, rest = line.partition(SEPARATOR)
    if not sep or not head.startswith(PREFIX):
        return False
    return rest.split(" ", 1)[0] in OWN_KINDS


def _bookmark(lines: list[str]) -> int:
    """Index just past the task's own last completed run, or 0.

    A failed run is deliberately not a bookmark: repeating a note is
    recoverable where losing one is not.
    """
    for i in range(len(lines) - 1, -1, -1):
        if _is_own_entry(lines[i]):
            return i + 1
    return 0


def read_journal(path: Path, limit: int = JOURNAL_LIMIT) -> str:
    """The journal as a prompt sees it: what is new, then what came before.

    Cut at the task's own last entry, so what is new is chosen by *position*:
    no quantity of notes can push another out before it has been seen once.
    Only the half allowed to age out is bounded.
    """
    lines = _entries(path)
    if not lines:
        return "nothing yet"

    at = _bookmark(lines)
    fresh, history = lines[at:], lines[:at]

    if not fresh:
        head = "Nothing new since you last worked."
    else:
        shown, waiting = fresh[:limit], max(0, len(fresh) - limit)
        # Oldest first, always: showing the newest would strand the oldest
        # forever, since the bookmark only moves as far as what was shown.
        head = "\n".join([NEW_HEADER, *shown])
        if waiting:
            head += f"\n({waiting} more waiting; you will see them next time)"

    if not history:
        return head
    tail = history[-limit:]
    omitted = ["(earlier entries omitted)"] if len(history) > limit else []
    return "\n".join([head, "", OLD_HEADER, *omitted, *tail])


def append_journal(
    path: Path,
    kind: str,
    text: str,
    *,
    title: str | None = None,
    when: datetime | None = None,
) -> None:
    """Add one line.

    ``kind`` is what wrote it: a run of this task says how it went, ``you`` is
    the user, ``task`` is a note from a sibling. Only ``did`` and ``nothing``
    count as the task's own, and so move the bookmark; see OWN_KINDS.
    """
    one_line = " ".join(str(text).split()) or "(nothing said)"
    if len(one_line) > JOURNAL_WIDTH:
        one_line = one_line[: JOURNAL_WIDTH - 3] + "..."
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")

    opening = "" if path.exists() else f"# {title or path.stem}\n\n"
    # `memory/shortterm/` need not exist yet: the first line a task writes is
    # what makes it.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{opening}- {stamp} · {kind:<8}{one_line}\n")
