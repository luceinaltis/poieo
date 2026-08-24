"""What a run leaves behind: one full record, so the project can learn.

The journal keeps one line per run and the event log clips what it shows;
this file keeps the whole result. Anything the project later claims to have
learned must be traceable to the work that taught it, and this record is
where such a trail ends -- it names the run, and the run's event log has the
rest.

The harness writes it, never the model: there is no tool for it, so nothing
depends on a model remembering to remember.

Spec: docs/superpowers/specs/2026-08-24-project-memory-design.md
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("poieo.memory")


def episodes_dir(project_dir: Path) -> Path:
    """Records live with the project's other machinery, never in `memory/`."""
    return project_dir / ".poieo" / "episodes"


def write_episode(task: Any, result: Any) -> Path | None:
    """One record per run, written once and never rewritten.

    Anchored to the task's own folder rather than wherever the run log was
    pointed: one project, one memory, however many configs drive it. The
    run id joins the two.

    Returns the path written, or None when nothing was -- already recorded,
    or unwritable. Memory is not worth killing a night's work over, so an
    unwritable record is logged and the run's result stands.
    """
    # Late: task.py imports this module, and the closing line's shape
    # belongs there, beside the journal it also feeds.
    from .task import _closing_line

    path = episodes_dir(task.dir) / f"{result.run_id}.json"
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
        "summary": _closing_line(result),
        "outputs": result.outputs,
    }
    try:
        if path.exists():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("task '%s': could not write the episode: %s", task.slug, exc)
        return None
    return path
