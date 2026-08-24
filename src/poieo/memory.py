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

from .blob import digest, kept
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


class _Links(BaseModel):
    """The typed claims an entry may make. A kind of connection exists only
    while a mechanism consumes it, so these two are all there are."""

    model_config = ConfigDict(extra="forbid")

    # What this entry needs to stay true. Followed forward at retrieval;
    # a lean on a set-aside entry earns a second-look line in the report.
    depends_on: list[str] = Field(default_factory=list)
    # A standing question for a person. Listed in the report, never followed.
    contradicts: list[str] = Field(default_factory=list)


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
    links: _Links = Field(default_factory=_Links)
    # Anchor path -> the digest of the content the entry was written
    # against. Written by the pass when it seals; a person may write one
    # by hand. Bytes live under .poieo/blobs/, never here.
    sealed: dict[str, str] = Field(default_factory=dict)


class Fact(BaseModel):
    """One learned entry: a slug, a body, and its frontmatter."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    slug: str
    body: str
    matter: _Frontmatter
    path: Path
    # [[names]] in the body: untyped, free to dangle -- a mention of an
    # entry that does not exist yet marks something worth writing.
    mentions: list[str] = Field(default_factory=list)


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
        # utf-8-sig: Notepad and friends write a BOM, and an invisible first
        # character must not silently turn the frontmatter into body text.
        matter, body = _split_frontmatter(path.read_text(encoding="utf-8-sig"))
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
    body = body.strip()
    mentions = list(dict.fromkeys(m.strip() for m in re.findall(r"\[\[([^\[\]]+)\]\]", body)))
    return Fact(slug=path.stem, body=body, matter=parsed, path=path, mentions=mentions)


def load_facts(project_dir: Path) -> list[Fact]:
    """Every learned entry, in a stable order. Malformed ones raise, so the
    caller decides whether that is a load failure or a 3am shrug."""
    root = memory_root(project_dir) / "facts"
    if not root.is_dir():
        return []
    return [_load_fact(p) for p in sorted(root.glob("*.md"))]


def check_memory(project_dir: Path) -> None:
    """Fail at launch, not at 3am: a typo in the memory must surface where
    `poieo validate` and the daemon's load can see it.

    Typed claims are checked against the whole folder here, because a single
    file cannot see its siblings. Prose mentions are deliberately not: a
    mention of an entry that does not exist marks something worth writing.
    """
    facts = load_facts(project_dir)
    known = {fact.slug for fact in facts}
    for fact in facts:
        claims = [
            ("depends_on", target) for target in fact.matter.links.depends_on
        ] + [("contradicts", target) for target in fact.matter.links.contradicts]
        if fact.matter.superseded_by is not None:
            claims.append(("superseded_by", fact.matter.superseded_by))
        for kind, target in claims:
            if target not in known:
                raise SpecError(
                    f"{fact.path}: {kind} names '{target}', and no such entry exists"
                )
        anchored = {anchor.split("::", 1)[0] for anchor in fact.matter.anchors}
        for path in fact.matter.sealed:
            if path not in anchored:
                raise SpecError(
                    f"{fact.path}: sealed names '{path}', which is not an anchor here"
                )


def _page(project_dir: Path) -> str | None:
    path = memory_root(project_dir) / CONSTITUTION
    try:
        text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
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
    chosen = _recall(project_dir, task, use_index=not preview) if task is not None else []
    if chosen:
        parts.append(LEARNED_HEADER + "\n\n" + "\n\n".join(fact.body for fact in chosen))
    return "\n\n".join(parts) or None


def memory_report(project_dir: Path) -> dict[str, Any] | None:
    """What `poieo memory` prints, or None when the project keeps none.

    The two connection sections are computed from the files at read time --
    no queue, no state, nothing written. A disagreement whose one side was
    set aside is resolved and disappears; whatever leaned on that side
    surfaces under second look instead.
    """
    if not memory_root(project_dir).is_dir():
        return None
    page = _page(project_dir)
    facts = _facts_or_less(project_dir)
    kept = [fact for fact in facts if fact.matter.superseded_by is None]
    kept_slugs = {fact.slug for fact in kept}

    disagreements = sorted(
        {
            tuple(sorted((fact.slug, other)))
            for fact in kept
            for other in fact.matter.links.contradicts
            if other in kept_slugs
        }
    )
    return {
        "page_chars": len(page or ""),
        "page_budget": PAGE_BUDGET,
        "kept": len(kept),
        "set_aside": len(facts) - len(kept),
        "lookup": "fast" if _fts_available() else "file-by-file",
        "disagreements": disagreements,
        "second_look": [reason for _, reason in doubts(project_dir, facts)],
        "accounting": _accounting(project_dir, facts),
    }


def _used_in(fact: Fact, record: dict[str, Any]) -> bool:
    """The one judgment of use, shared by wear and the accounting so the
    two can never disagree: the entry's distinctive words surface in what
    the run itself produced -- a behavioral stand-in until a serving stack
    can report attention."""
    said = _tokens(
        f"{record.get('summary', '')} "
        f"{json.dumps(record.get('outputs', {}), ensure_ascii=False)}"
    )
    return len(_tokens(fact.body) & said) >= 2


# How far back the accounting reads, and how often an entry must have been
# shown, unused, before it is worth naming.
ACCOUNT_WINDOW = 50
UNUSED_FLOOR = 3


def _accounting(project_dir: Path, facts: list[Fact]) -> dict[str, Any] | None:
    """Is the memory earning its keep? A read over the recent run records,
    never a stored counter, and nothing anywhere acts on it."""
    root = project_dir / ".poieo" / "episodes"
    if not root.is_dir():
        return None
    by_slug = {fact.slug: fact for fact in facts}
    runs_shown = runs_used = 0
    shown_count: dict[str, int] = {}
    used_count: dict[str, int] = {}
    for path in sorted(root.glob("*.json"), reverse=True)[:ACCOUNT_WINDOW]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") != "completed":
            continue
        shown = record.get("shown") or []
        if not shown:
            continue
        runs_shown += 1
        any_used = False
        for slug in shown:
            shown_count[slug] = shown_count.get(slug, 0) + 1
            fact = by_slug.get(slug)
            if fact is not None and _used_in(fact, record):
                used_count[slug] = used_count.get(slug, 0) + 1
                any_used = True
        if any_used:
            runs_used += 1
    if runs_shown == 0:
        return None
    unused = sorted(
        (slug, count)
        for slug, count in shown_count.items()
        if count >= UNUSED_FLOOR
        and used_count.get(slug, 0) == 0
        # Only entries still standing: a set-aside one was already judged,
        # and naming it again is stale advice.
        and slug in by_slug
        and by_slug[slug].matter.superseded_by is None
    )
    return {"runs_shown": runs_shown, "runs_used": runs_used, "unused": unused}


def doubts(
    project_dir: Path, facts: list[Fact] | None = None
) -> list[tuple[str, str]]:
    """Every kept entry worth a second look, with the sentence that says
    why: a lean on a set-aside entry, an anchor whose target is gone, or a
    target that changed after the entry was last written (editing the entry
    is how a person clears that one -- look, then touch). Computed from the
    files every time; nothing writes a queue."""
    facts = _facts_or_less(project_dir) if facts is None else facts
    aside = {fact.slug for fact in facts if fact.matter.superseded_by is not None}
    out: list[tuple[str, str]] = []
    for fact in facts:
        if fact.matter.superseded_by is not None:
            continue
        for target in fact.matter.links.depends_on:
            if target in aside:
                out.append(
                    (fact.slug, f"{fact.slug} leans on {target}, which is set aside")
                )
        for anchor in fact.matter.anchors:
            part = anchor.split("::", 1)[0]
            named = project_dir / part
            try:
                if not named.exists():
                    out.append((fact.slug, f"{fact.slug} names {anchor}, which is gone"))
                    continue
                seal = fact.matter.sealed.get(part)
                if seal is not None and kept(project_dir, seal) is not None:
                    # Sealed: doubt by content, not clocks. A touched-but-
                    # identical file raises nothing; the line only fires
                    # when the bytes really differ from the keepsake.
                    if digest(named) != seal:
                        out.append(
                            (
                                fact.slug,
                                f"{fact.slug} names {anchor}, which no longer "
                                "matches what it was written against",
                            )
                        )
                elif named.stat().st_mtime_ns > fact.path.stat().st_mtime_ns:
                    out.append(
                        (
                            fact.slug,
                            f"{fact.slug} names {anchor}, "
                            "which changed after it was written",
                        )
                    )
            except OSError:
                # Unreadable is present: upkeep never turns an I/O hiccup
                # into doubt.
                pass
    return sorted(out)


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


def _recall(project_dir: Path, task: Any, use_index: bool = True) -> list[Fact]:
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

    # Association after evidence: a neighbor has no score of its own to
    # argue with -- its claim to the prompt is its seed's, times how worn
    # the connection between them is. Neighbors are drawn from the
    # already-filtered pool, which is what keeps scope and set-aside
    # holding through connections; a second hop is taken only across a
    # worn connection, so with no wear anywhere one hop means one hop and
    # the order is exactly what the connections slice shipped.
    from .strength import WORN_FLOOR, wear_of

    worn = wear_of(project_dir)
    sequence = [fact for _, fact in scored]
    taken = {fact.slug for fact in sequence}

    carry: dict[str, float] = {}
    for rank, (_, fact) in enumerate(scored):
        for neighbor in _connected(fact, facts):
            if neighbor.slug in taken:
                continue
            wear = worn.get(frozenset((fact.slug, neighbor.slug)), 0.0)
            carry[neighbor.slug] = carry.get(neighbor.slug, 0.0) + (1.0 + wear) / (1 + rank)

    by_slug = {fact.slug: fact for fact in facts}
    further: dict[str, float] = {}
    for slug, reached in carry.items():
        for neighbor in _connected(by_slug[slug], facts):
            if neighbor.slug in taken or neighbor.slug in carry:
                continue
            wear = worn.get(frozenset((slug, neighbor.slug)), 0.0)
            if wear >= WORN_FLOOR:
                further[neighbor.slug] = further.get(neighbor.slug, 0.0) + reached * wear

    carry.update(further)
    sequence += sorted(
        (by_slug[slug] for slug in carry),
        key=lambda fact: (-carry[fact.slug], fact.slug),
    )

    chosen: list[Fact] = []
    spent = 0
    for fact in sequence:
        if spent + len(fact.body) > FACTS_BUDGET:
            break
        chosen.append(fact)
        spent += len(fact.body)
    return chosen


def _connected(fact: Fact, eligible: list[Fact]) -> list[Fact]:
    """Who arrives beside this entry: mentions either way (nearness is
    symmetric), leans-on forward only (what you chose needs what it leans
    on, not the reverse), disagrees never (its consumer is the report --
    dragging a disputed entry in by association is how confusion spreads).
    """
    named = set(fact.mentions) | set(fact.matter.links.depends_on)
    return sorted(
        (
            other
            for other in eligible
            if other.slug != fact.slug
            and (other.slug in named or fact.slug in other.mentions)
        ),
        key=lambda other: other.slug,
    )


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
        # What the project had in mind: the same selection that built the
        # run's block, recomputed at record time. Emphasis-grade, so it may
        # fail without costing the record, let alone the run.
        if memory_root(task.dir).is_dir():
            record["shown"] = [fact.slug for fact in _recall(task.dir, task)]
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
        log.warning("task '%s': could not write the episode: %s", task.slug, exc)
        return None
    return path
