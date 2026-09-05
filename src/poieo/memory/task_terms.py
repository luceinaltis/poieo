"""What else a task could be called, kept beside the memory and matched with
its own words.

Recall asks with a card's name, prompt and folder. A lesson worded in other
words is not reached, so a card may carry terms of its own -- the other words
the same work could be described with -- and they widen what recall asks with.
Measured on the hand-written cases: with terms on the lesson side alone 7/10
of differently-worded lessons were found; with both sides, 9/10.

**Stamped, not hooked.** A card is a file a person owns and edits, on the board
or by hand, and nothing is written back into it. Its terms live under
`memory/cache/`, each with a digest of the card text they were written
against. A card edited since is simply not widened -- today's behaviour, never
a wait -- until the learning pass writes fresh terms for it. A save hook could
not promise that; the stamp can.

Design: docs/memory.md
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from ..layout import layout_for

log = logging.getLogger("poieo.memory")


def stamp_of(task: Any) -> str:
    """The card as recall sees it, digested: the same three fields the seed
    is built from, so terms go stale exactly when the seed would change."""
    text = f"{task.name}\n{task.prompt or ''}\n{task.folder or ''}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _path(project_dir: Path) -> Path:
    return layout_for(project_dir).task_terms()


def _read(project_dir: Path) -> dict[str, dict[str, str]]:
    path = _path(project_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Derived, and a wrong file must not cost a run: read as empty.
        log.warning("could not read the task terms at %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def task_terms(project_dir: Path, task: Any) -> str:
    """This card's terms, or nothing when there are none or the card has
    changed since they were written."""
    try:
        kept = _read(project_dir).get(task.slug)
    except Exception:  # noqa: BLE001 -- a task with no slug yet is a task with no terms
        return ""
    if not isinstance(kept, dict) or kept.get("stamp") != stamp_of(task):
        return ""
    words = kept.get("terms")
    return words if isinstance(words, str) else ""


def stale(project_dir: Path, tasks: list[Any]) -> list[Any]:
    """The cards whose terms are missing or were written against other text."""
    kept = _read(project_dir)
    out = []
    for task in tasks:
        have = kept.get(task.slug)
        if not isinstance(have, dict) or have.get("stamp") != stamp_of(task):
            out.append(task)
    return out


def remember(project_dir: Path, task: Any, terms: str) -> None:
    """Write this card's terms, stamped with the text they were written for.
    Written tmp-and-rename so a torn write cannot leave half a file."""
    path = _path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read(project_dir)
    data[task.slug] = {"stamp": stamp_of(task), "terms": " ".join(terms.split())}
    scratch = path.with_suffix(".tmp")
    scratch.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scratch.replace(path)
