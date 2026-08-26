"""What a run leaves behind when it is over.

One file per run, written once and never rewritten, so anything remembered
can be traced to the work that taught it. The harness writes these, never the
model: there is no tool for it, so nothing depends on a model remembering to
remember.

It sits in ``runs/results/``, beside the event stream the same run wrote to
``runs/events/``. They share a run id and are two halves of one account: the
stream as it happened, and what was left when it stopped.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..layout import layout_for
from .facts import Fact, keeps_memory, tokens
from .recall import recall

log = logging.getLogger("poieo.memory")


def results_dir(project_dir: Path) -> Path:
    """Beside the events of the same runs, never in `memory/`: what a person
    keeps and what a night produced are different kinds of thing.

    ``layout_for``, not a layout rooted here: the events of these same runs
    are written by ``RunStore``, which is handed the project's ``runs/`` --
    and that folder answers to ``store:``. Rooting this at the folder it was
    asked from instead put the result of a run in one place and its events in
    another, which is a run history split down the middle by nothing.
    """
    return layout_for(project_dir).results()


def used_in(fact: Fact, record: dict[str, Any]) -> bool:
    """The one judgment of use, shared by wear and the accounting so the
    two can never disagree: the entry's distinctive words surface in what
    the run itself produced -- a behavioral stand-in until a serving stack
    can report attention."""
    said = tokens(
        f"{record.get('summary', '')} "
        f"{json.dumps(record.get('outputs', {}), ensure_ascii=False)}"
    )
    return len(tokens(fact.body) & said) >= 2


def write_result(task: Any, result: Any) -> Path | None:
    """One record per run, written once and never rewritten.

    Anchored to the task's own folder rather than wherever the run log was
    pointed: one project, one memory, however many configs drive it. The
    run id joins the two.

    Returns the path written, or None when nothing was -- already recorded,
    or unwritable. Memory is not worth killing a night's work over, so an
    unwritable record is logged and the run's result stands.
    """
    # Late: task.py imports this package, and the closing line's shape
    # belongs there, beside the journal it also feeds.
    from ..task import closing_line

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
        # What the project had in mind: the same selection that built the
        # run's block, recomputed at record time. Emphasis-grade, so it may
        # fail without costing the record, let alone the run.
        if keeps_memory(task.dir):
            record["shown"] = [fact.slug for fact in recall(task.dir, task)]
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
