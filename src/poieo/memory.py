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

import hashlib
import json
import logging
import re
import sqlite3
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .errors import SpecError, describe_invalid

log = logging.getLogger("poieo.memory")

MEMORY_DIR = "memory"
CONSTITUTION = "constitution.md"
INDEX_NAME = "memory.sqlite3"
# Character budget (~3k tokens) for the always-present page. Advisory: the
# page is the user's to trim, and refusing to run over page length would
# make the memory a way to break the daemon.
PAGE_BUDGET = 12_000
# Budget for the learned entries that follow the page. Cut on whole-entry
# boundaries, best first -- half a lesson is worse than none.
FACTS_BUDGET = 4_000
# An entry anchored where the task works beats any merely-similar one.
_ANCHOR_BOOST = 1_000

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
    # Markdown comments are notes to the page's editor, not to the model,
    # and the page is the most expensive room in the prompt.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
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


def read_memory(
    project_dir: Path, task: Any | None = None, *, preview: bool = False
) -> str | None:
    """The block a run is shown, or None when there is nothing to show.

    Re-read every run, like the journal. The page comes first and whole --
    its position is fixed so the stable part of the prompt stays stable --
    and the entries ``task`` earned follow it, best first, cut on whole-entry
    boundaries. The page never competes with them for room.

    ``preview`` answers the same question without leaving a trace: the file
    scan gives the same entries the index would, so `poieo memory` can show
    exactly what a run will see while writing nothing at all.
    """
    parts = []
    page = _page(project_dir)
    if page is not None:
        parts.append(f"{PAGE_HEADER}\n{page}")
    learned = _recall(project_dir, task, use_index=not preview) if task is not None else []
    if learned:
        parts.append(LEARNED_HEADER + "\n\n" + "\n\n".join(learned))
    return "\n\n".join(parts) or None


def memory_report(project_dir: Path) -> dict[str, Any] | None:
    """What `poieo memory` prints, or None when the project keeps none."""
    if not memory_root(project_dir).is_dir():
        return None
    page = _page(project_dir)
    facts = _facts_or_less(project_dir)
    kept = sum(1 for fact in facts if fact.matter.superseded_by is None)
    return {
        "page_chars": len(page or ""),
        "page_budget": PAGE_BUDGET,
        "kept": kept,
        "set_aside": len(facts) - kept,
        "lookup": "fast" if _fts_available() else "file-by-file",
    }


# -- choosing what a task is shown -------------------------------------------


# Glue words carry no signal, and one shared "the" must not make an entry
# relevant to everything.
_GLUE = frozenset(
    "a an and are as at be but by for from if in is it no not of on or so "
    "that the this to was were will with you".split()
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower())) - _GLUE


def _facts_or_less(project_dir: Path) -> list[Fact]:
    """Every entry that still reads, for the run path. A malformed one is a
    load failure when loading (check_memory); mid-residency it is skipped --
    a run with less in mind beats no run at all."""
    root = memory_root(project_dir) / "facts"
    if not root.is_dir():
        return []
    facts = []
    for path in sorted(root.glob("*.md")):
        try:
            facts.append(_load_fact(path))
        except SpecError as exc:
            log.warning("%s; leaving it out of this run", exc)
    return facts


def _in_scope(fact: Fact, task: Any, project_dir: Path) -> bool:
    """A filter over one store, never a wall: the word that means everyone,
    the task's own name, or a path that covers where it works."""
    folder = task.folder_path()
    for entry in fact.matter.scope:
        if entry in ("global", task.slug):
            return True
        base = (project_dir / entry).resolve()
        if folder == base or folder.is_relative_to(base):
            return True
    return False


def _anchored(fact: Fact, task: Any, project_dir: Path) -> bool:
    """Anchor paths are written relative to the project (the tasks folder)."""
    folder = task.folder_path()
    for anchor in fact.matter.anchors:
        target = (project_dir / anchor.split("::", 1)[0]).resolve()
        if target == folder or target.is_relative_to(folder) or folder.is_relative_to(target):
            return True
    return False


def _recall(project_dir: Path, task: Any, use_index: bool = True) -> list[str]:
    """The entries this task earned, ranked, in budget. Never the page's room."""
    facts = [
        fact
        for fact in _facts_or_less(project_dir)
        if fact.matter.superseded_by is None and _in_scope(fact, task, project_dir)
    ]
    if not facts:
        return []
    seed = _tokens(f"{task.name} {task.prompt or ''} {task.folder}")

    # An anchored entry is relevant by where it points, not by the words it
    # shares, so it must not depend on the index finding a shared word.
    candidates = _candidates(project_dir, facts, seed) if use_index else facts
    pool = {fact.slug: fact for fact in candidates}
    for fact in facts:
        if _anchored(fact, task, project_dir):
            pool.setdefault(fact.slug, fact)

    scored = []
    for fact in pool.values():
        score = len(seed & _tokens(fact.body))
        if _anchored(fact, task, project_dir):
            score += _ANCHOR_BOOST
        if score > 0:
            scored.append((score, fact))
    scored.sort(key=lambda pair: (-pair[0], pair[1].slug))

    chosen: list[str] = []
    spent = 0
    for _, fact in scored:
        if spent + len(fact.body) > FACTS_BUDGET:
            break
        chosen.append(fact.body)
        spent += len(fact.body)
    return chosen


# -- the derived index -------------------------------------------------------
#
# Never the truth: built from the entry files, checked against them by
# fingerprint, rebuilt without being asked when missing, stale, or corrupt.
# Deleting it loses nothing. Any trouble here degrades to reading the files,
# never to a failed run.


@lru_cache(maxsize=None)
def _fts_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE probe USING fts5(body)")
        finally:
            con.close()
        return True
    except sqlite3.Error:
        log.info("this Python build has no FTS5; memory lookup reads the files instead")
        return False


def _candidates(project_dir: Path, facts: list[Fact], seed: set[str]) -> list[Fact]:
    """Who is worth scoring. The index narrows when it can; the final ranking
    is the same plain arithmetic either way, which is what makes the slower
    path the same feature."""
    if not seed or not _fts_available():
        return facts
    try:
        con = _open_index(project_dir, facts)
        try:
            rows = con.execute(
                "SELECT slug FROM facts_fts WHERE facts_fts MATCH ?",
                (" OR ".join(sorted(seed)),),
            ).fetchall()
        finally:
            con.close()
        hits = {row[0] for row in rows}
        return [fact for fact in facts if fact.slug in hits]
    except (sqlite3.Error, OSError) as exc:
        log.warning("memory index unavailable (%s); reading the files instead", exc)
        return facts


def _fingerprint(facts: list[Fact]) -> str:
    parts = sorted(f"{fact.path.name}:{fact.path.stat().st_mtime_ns}" for fact in facts)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _open_index(project_dir: Path, facts: list[Fact]) -> sqlite3.Connection:
    path = project_dir / ".poieo" / INDEX_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = _fingerprint(facts)
    con = sqlite3.connect(path, timeout=5)
    try:
        row = con.execute("SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
        if row and row[0] == stamp:
            return con
    except sqlite3.Error:
        pass  # missing tables, or not even a database: rebuild below
    try:
        _rebuild(con, facts, stamp)
        return con
    except sqlite3.Error:
        con.close()
        path.unlink(missing_ok=True)
        con = sqlite3.connect(path, timeout=5)
        _rebuild(con, facts, stamp)
        return con


def _rebuild(con: sqlite3.Connection, facts: list[Fact], stamp: str) -> None:
    con.executescript(
        "DROP TABLE IF EXISTS facts_fts;"
        "DROP TABLE IF EXISTS meta;"
        "CREATE VIRTUAL TABLE facts_fts USING fts5(slug UNINDEXED, body);"
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
    )
    con.executemany(
        "INSERT INTO facts_fts(slug, body) VALUES(?, ?)",
        [(fact.slug, fact.body) for fact in facts],
    )
    con.execute("INSERT INTO meta VALUES('fingerprint', ?)", (stamp,))
    con.commit()


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
