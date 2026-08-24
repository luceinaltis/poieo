"""The project's memory: what it always requires, and what it has learned.

A task's journal is short-term on purpose -- old lines age out of the
prompt. This module is the long-term half: one page in front of every run,
one file per learned entry, and one full record left behind by every run so
anything remembered can be traced to the work that taught it.

Truth lives in markdown under git (`memory/`); everything a machine derives
lives under `.poieo/` and can be deleted without loss. The harness writes
the records, never the model: there is no tool for it, so nothing depends
on a model remembering to remember.

Spec: docs/superpowers/specs/2026-08-24-project-memory-design.md
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .errors import SpecError, describe_invalid

log = logging.getLogger("poieo.memory")

MEMORY_DIR = "memory"
CONSTITUTION = "constitution.md"
# Character budget (~3k tokens) for the always-present page. Advisory: the
# page is the user's to trim, and refusing to run over page length would
# make the memory a way to break the daemon.
PAGE_BUDGET = 12_000

# Interface words only past this point: the machinery names (tiers, facts,
# retrieval) stay in this module and the spec.
PAGE_HEADER = "What this project always requires:"
LEARNED_HEADER = "What earlier work here has learned:"


# -- the page and what was learned -------------------------------------------


class _Frontmatter(BaseModel):
    """What a learned entry may say about itself. Anything else is a typo."""

    model_config = ConfigDict(extra="forbid")

    # A filter over one store, never a wall: task slugs, path prefixes,
    # or the word that means everyone.
    scope: list[str] = Field(default_factory=lambda: ["global"])
    # "path" or "path::symbol" -- no line numbers, they rot fastest.
    anchors: list[str] = Field(default_factory=list)
    # Run ids of the episodes that taught it. Empty means a person did.
    source: list[str] = Field(default_factory=list)
    # Event time only; git already records when every line was written.
    valid_from: date | None = None
    # Set this instead of deleting: the file stays, retrieval moves on.
    superseded_by: str | None = None


class Fact(BaseModel):
    """One learned entry: a slug, a body, and its frontmatter."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    slug: str
    body: str
    matter: _Frontmatter
    path: Path


def memory_root(project_dir: Path) -> Path:
    return project_dir / MEMORY_DIR


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            matter = yaml.safe_load("\n".join(lines[1:i])) or {}
            if not isinstance(matter, dict):
                raise ValueError("the frontmatter must be a mapping")
            return matter, "\n".join(lines[i + 1 :])
    raise ValueError("the frontmatter never closes")


def _load_fact(path: Path) -> Fact:
    try:
        matter, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        parsed = _Frontmatter.model_validate(matter)
        if not body.strip():
            raise ValueError("an entry needs something to say")
    except OSError as exc:
        raise SpecError(f"{path}: could not read: {exc}") from exc
    except (ValueError, yaml.YAMLError) as exc:
        raise SpecError(
            f"{path}: invalid memory entry: "
            f"{describe_invalid(exc, tuple(_Frontmatter.model_fields))}"
        ) from exc
    return Fact(slug=path.stem, body=body.strip(), matter=parsed, path=path)


def load_facts(project_dir: Path) -> list[Fact]:
    """Every learned entry, in a stable order. Malformed ones raise, so the
    caller decides whether that is a load failure or a 3am shrug."""
    root = memory_root(project_dir) / "facts"
    if not root.is_dir():
        return []
    return [_load_fact(p) for p in sorted(root.glob("*.md"))]


def check_memory(project_dir: Path) -> None:
    """Fail at launch, not at 3am: a typo in the memory must surface where
    `poieo validate` and the daemon's load can see it."""
    load_facts(project_dir)


def _page(project_dir: Path) -> str | None:
    path = memory_root(project_dir) / CONSTITUTION
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError as exc:
        # Forgetting beats failing: the run proceeds with less in mind.
        log.warning("could not read the memory page %s: %s", path, exc)
        text = ""
    text = text.strip()
    if not text:
        return None
    if len(text) > PAGE_BUDGET:
        log.warning(
            "the memory page %s runs %d characters against a budget of %d; "
            "trim it -- every run of every task reads it whole",
            path,
            len(text),
            PAGE_BUDGET,
        )
    return text


def read_memory(project_dir: Path, task: Any | None = None) -> str | None:
    """The block a run is shown, or None when there is nothing to show.

    Re-read every run, like the journal. The page comes first and whole --
    its position is fixed so the stable part of the prompt stays stable.
    ``task`` will choose which learned entries follow it; this slice
    carries the page alone.
    """
    page = _page(project_dir)
    if page is None:
        return None
    return f"{PAGE_HEADER}\n{page}"


# -- the record every run leaves ---------------------------------------------


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
