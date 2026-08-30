"""Choosing what a task is shown, and assembling the block it reads.

The page comes first and whole, so the stable part of the prompt stays stable;
the entries the task earned follow it, best first, on whole-entry boundaries.
The page never competes with them for room.

**The lookup is asked before anything is read.** Candidates are narrowed first
and only the winners are fetched -- reading every entry to choose forty is the
one thing this file must not do.

Design: docs/memory.md
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..layout import layout_for
from .entries import Entry, entry_of, keeps_memory, open_memory, read_page, words
from .index import narrow

# Budget for the learned entries that follow the page. Cut on whole-entry
# boundaries, best first -- half a lesson is worse than none.
ENTRIES_BUDGET = 4_000
# An entry anchored where the task works beats any merely-similar one.
_ANCHOR_BOOST = 1_000

# Interface words only past this point: the machinery names (entries, recall)
# stay in this package and the spec. docs/memory.md pairs the two lists.
PAGE_HEADER = "What this project always requires:"
LEARNED_HEADER = "What earlier work here has learned:"


def read_memory(project_dir: Path, task: Any | None = None, *, preview: bool = False) -> str | None:
    """The block a run is shown, or None when there is nothing to show.

    Re-read every run, like the journal. ``preview`` answers the same question
    without leaving a trace, so `poieo memory` can show what a run will see
    while writing nothing at all.
    """
    parts = []
    text = read_page(project_dir)
    if text is not None:
        parts.append(f"{PAGE_HEADER}\n{text}")
    chosen = recall(project_dir, task, use_index=not preview) if task is not None else []
    if chosen:
        parts.append(LEARNED_HEADER + "\n\n" + "\n\n".join(entry.body for entry in chosen))
    return "\n\n".join(parts) or None


def _in_scope(entry: Entry, task: Any, project_dir: Path) -> bool:
    """A filter over one store, never a wall: the word that means everyone,
    the task's own name, or a path that covers where it works."""
    folder = task.folder_path()  # None for a task that works on no folder
    for named in entry.matter.scope:
        if named in ("global", task.slug):
            return True
        base = (layout_for(project_dir).root / named).resolve()
        if folder is not None and (folder == base or folder.is_relative_to(base)):
            return True
    return False


def _anchored(entry: Entry, task: Any, project_dir: Path) -> bool:
    """Anchor paths are written relative to the project -- the folder the
    `poieo.yaml` sits in, which is also where the memory does."""
    folder = task.folder_path()
    for anchor in entry.matter.anchors:
        target = (layout_for(project_dir).root / anchor.split("::", 1)[0]).resolve()
        if folder is None:
            continue  # a task that works on no folder is covered by no anchor
        if target == folder or target.is_relative_to(folder) or folder.is_relative_to(target):
            return True
    return False


def _fetch(con: sqlite3.Connection, slugs: list[str]) -> list[Entry]:
    if not slugs:
        return []
    holes = ",".join("?" * len(slugs))
    rows = con.execute(f"SELECT * FROM entries WHERE slug IN ({holes})", slugs).fetchall()
    return [entry_of(row) for row in rows]


def _pool(con: sqlite3.Connection, seed: set[str], use_index: bool) -> list[Entry]:
    """The entries worth scoring, fetched and no more.

    An anchored entry is relevant by where it points, not by the words it
    shares, so it must not depend on the lookup finding a shared word -- it is
    asked for by the one thing the row already knows, that it has anchors.
    """
    hits = narrow(con, seed) if use_index else None
    if hits is None:
        return [entry_of(row) for row in con.execute("SELECT * FROM entries").fetchall()]
    names = sorted(hits)
    if not names:
        rows = con.execute("SELECT * FROM entries WHERE anchors != '[]'").fetchall()
    else:
        holes = ",".join("?" * len(names))
        rows = con.execute(f"SELECT * FROM entries WHERE slug IN ({holes}) OR anchors != '[]'", names).fetchall()
    return [entry_of(row) for row in rows]


def _neighbours(con: sqlite3.Connection, slugs: set[str]) -> list[Entry]:
    """Entries one link away from any of these, in either direction.

    Fetched by name through the link table rather than found by reading every
    entry -- association is why the memory is a graph, and it must not be the
    reason the whole graph is loaded.
    """
    if not slugs:
        return []
    holes = ",".join("?" * len(slugs))
    names = sorted(slugs)
    rows = con.execute(
        f"SELECT target AS other FROM links WHERE slug IN ({holes})"
        "   AND kind IN ('mentions', 'depends_on')"
        f" UNION SELECT slug AS other FROM links WHERE target IN ({holes})"
        "   AND kind = 'mentions'",
        names + names,
    ).fetchall()
    return _fetch(con, sorted({row["other"] for row in rows} - slugs))


def recall(project_dir: Path, task: Any, use_index: bool = True) -> list[Entry]:
    """The entries this task earned, ranked, in budget. Never the page's room."""
    if not keeps_memory(project_dir):
        return []
    seed = words(f"{task.name} {task.prompt or ''} {task.folder}")

    def allowed(entries: list[Entry]) -> list[Entry]:
        return [
            entry for entry in entries if entry.matter.superseded_by is None and _in_scope(entry, task, project_dir)
        ]

    from ..strength import STRONG_FLOOR, strengths

    strength = strengths(project_dir)

    with open_memory(project_dir) as con:
        candidates = allowed(_pool(con, seed, use_index))
        if not candidates:
            return []

        scored = []
        for entry in candidates:
            score = len(seed & words(entry.body))
            if _anchored(entry, task, project_dir):
                score += _ANCHOR_BOOST
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda pair: (-pair[0], pair[1].slug))

        # Association after evidence: a neighbour's claim is its seed's,
        # divided by rank and scaled by how strong the connection is. Scope and
        # set-aside hold through connections; a second hop needs a strong
        # connection, so with nothing reinforced one hop means one hop.
        sequence = [entry for _, entry in scored]
        taken = {entry.slug for entry in sequence}
        by_slug = {entry.slug: entry for entry in sequence}

        first = allowed(_neighbours(con, taken))
        by_slug |= {entry.slug: entry for entry in first}

        carry: dict[str, float] = {}
        for rank, (_, entry) in enumerate(scored):
            for neighbor in connected(entry, first):
                if neighbor.slug in taken:
                    continue
                weight = strength.get(frozenset((entry.slug, neighbor.slug)), 0.0)
                carry[neighbor.slug] = carry.get(neighbor.slug, 0.0) + (1.0 + weight) / (1 + rank)

        second = allowed(_neighbours(con, set(carry)))
        by_slug |= {entry.slug: entry for entry in second}

    further: dict[str, float] = {}
    for slug, reached in carry.items():
        for neighbor in connected(by_slug[slug], second):
            if neighbor.slug in taken or neighbor.slug in carry:
                continue
            weight = strength.get(frozenset((slug, neighbor.slug)), 0.0)
            if weight >= STRONG_FLOOR:
                further[neighbor.slug] = further.get(neighbor.slug, 0.0) + reached * weight

    carry.update(further)
    sequence += sorted(
        (by_slug[slug] for slug in carry),
        key=lambda entry: (-carry[entry.slug], entry.slug),
    )

    # One entry too big for the budget loses its own place, not everybody
    # else's: the room it could not use goes to whoever ranks below it.
    chosen: list[Entry] = []
    spent = 0
    for entry in sequence:
        if spent + len(entry.body) > ENTRIES_BUDGET:
            continue
        chosen.append(entry)
        spent += len(entry.body)
    return chosen


def connected(entry: Entry, eligible: list[Entry]) -> list[Entry]:
    """Who arrives beside this entry.

    Mentions count either way (nearness is symmetric); ``depends_on`` forward
    only (what you chose needs what it leans on, not the reverse); and
    ``contradicts`` is a **veto**, not one vote -- "this disputes [[x]]" is an
    ordinary way to write a disagreement, and the mention in it must not
    smuggle the disputed entry into a prompt.
    """
    named = set(entry.mentions) | set(entry.matter.links.depends_on)
    return sorted(
        (
            other
            for other in eligible
            if other.slug != entry.slug
            and (other.slug in named or entry.slug in other.mentions)
            and other.slug not in entry.matter.links.contradicts
            and entry.slug not in other.matter.links.contradicts
        ),
        key=lambda other: other.slug,
    )
