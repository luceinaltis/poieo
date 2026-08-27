"""What a run leaves behind when it is over.

One file per run in ``runs/results/``, written once and never rewritten,
sharing a run id with the events the same run wrote to ``runs/events/``.

The harness writes these, never the model: there is no tool for it, so nothing
depends on a model remembering to remember.

Design: docs/memory.md
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..layout import layout_for
from .entries import Entry, keeps_memory, words
from .recall import recall

log = logging.getLogger("poieo.memory")


def results_dir(project_dir: Path) -> Path:
    # `layout_for`, not a layout rooted here: `runs/` answers to `store:`, and
    # rooting this at the folder asked from would put a run's result and its
    # events in two different places.
    return layout_for(project_dir).results()


def used_in(entry: Entry, record: dict[str, Any]) -> bool:
    """Did this entry do real work in this run?

    The entry's distinctive words surface in what the run produced -- a
    behavioural stand-in until a serving stack can report attention. Shared by
    reinforcement and the accounting, so the two can never disagree.
    """
    said = words(
        f"{record.get('summary', '')} "
        f"{json.dumps(record.get('outputs', {}), ensure_ascii=False)}"
    )
    return len(words(entry.body) & said) >= 2


def write_result(task: Any, result: Any) -> Path | None:
    """One record per run, anchored to the task's folder: one project, one
    memory, however many configs drive it.

    Returns the path written, or None when nothing was -- already recorded, or
    unwritable. Memory is not worth killing a night's work over.
    """
    from ..task import closing_line  # late: task.py imports this package

    path = results_dir(task.dir) / f"{result.run_id}.json"
    record = {
        "run_id": result.run_id,
        "task": task.slug,
        "name": task.name,
        "folder": str(task.folder_path()),
        "status": result.status,
        "error": result.error,
        "iteration": result.iteration,
        "steps": result.steps,
        "path": list(result.path),
        "usage": dict(result.usage),
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "summary": closing_line(result),
        "outputs": result.outputs,
    }
    try:
        # Recomputed rather than passed in, and emphasis-grade: it may fail
        # without costing the record, let alone the run.
        if keeps_memory(task.dir):
            record["shown"] = [entry.slug for entry in recall(task.dir, task)]
    except Exception as exc:
        log.warning("task '%s': could not record what was shown: %s", task.slug, exc)
    try:
        if path.exists():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("task '%s': could not write the result: %s", task.slug, exc)
        return None
    return path
