"""Which of the entries a task would be shown actually apply to it -- asked of
a model once, kept beside the memory, and read at recall for free.

Every way of widening what a task matches raises recall and brings the
look-alike with it: a lesson about a neighbouring system with the opposite
advice, sharing the task's words by construction. No signal that scores words
separates the two, and measured on three corpora nobody here wrote nothing did
-- until the candidates were put to a model with the task and what it rejected
was dropped. That held recall and took the look-alike from ten in ten to nought,
at nought to three right answers dropped per hundred.

**Cached, never asked at recall.** A run reads memory without a model, and this
keeps it so: the verdict is written by the learning schedule and keyed by the
card's text and by the candidate set it was given -- each entry's name and when
it last changed -- so a card edited, or a memory that has learned since, is
simply not judged until the next pass. Today's block, never a wait.

Design: docs/memory.md
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from ..layout import layout_for
from .entries import Entry

log = logging.getLogger("poieo.memory")


def stamp_of(task: Any) -> str:
    """The card as recall sees it, digested."""
    text = f"{task.name}\n{task.prompt or ''}\n{task.folder or ''}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def candidates_stamp(entries: list[Entry]) -> str:
    """The candidate set, digested: each entry's name and when it last changed,
    so a verdict goes stale when any of them is rewritten or replaced."""
    text = "|".join(sorted(f"{e.slug}@{e.updated_at.isoformat()}" for e in entries))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _path(project_dir: Path) -> Path:
    return layout_for(project_dir).judgements()


def _read(project_dir: Path) -> dict[str, dict[str, Any]]:
    path = _path(project_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read the judgements at %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def judgement(project_dir: Path, task: Any, entries: list[Entry]) -> set[str] | None:
    """The slugs a judge kept for this task over exactly these candidates, or
    None when there is no verdict for this card and this set -- in which case
    the caller shows the candidates as they are."""
    try:
        kept = _read(project_dir).get(task.slug)
    except Exception:  # noqa: BLE001 -- a task with no slug yet has no verdict
        return None
    if not isinstance(kept, dict):
        return None
    if kept.get("stamp") != stamp_of(task) or kept.get("candidates") != candidates_stamp(entries):
        return None
    keep = kept.get("keep")
    return {s for s in keep if isinstance(s, str)} if isinstance(keep, list) else None


def is_stale(project_dir: Path, task: Any, entries: list[Entry]) -> bool:
    return judgement(project_dir, task, entries) is None


def remember(project_dir: Path, task: Any, entries: list[Entry], keep: list[str]) -> None:
    """Write the verdict for this card over these candidates. Written
    tmp-and-rename so a torn write cannot leave half a file."""
    path = _path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read(project_dir)
    data[task.slug] = {
        "stamp": stamp_of(task),
        "candidates": candidates_stamp(entries),
        "keep": sorted(set(keep)),
    }
    scratch = path.with_suffix(".tmp")
    scratch.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scratch.replace(path)


def candidates(project_dir: Path, task: Any) -> list[Entry]:
    """What this task would be shown before any verdict -- exactly the set a
    judge is handed, and the set a verdict is keyed to."""
    from .recall import recall  # late: recall imports this module

    return recall(project_dir, task, judge=False)
