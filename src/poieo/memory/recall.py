"""Choosing what a task is shown, and assembling the block it reads.

The page comes first and whole, so the stable part of the prompt stays stable;
the entries the task earned follow it, best first, on whole-entry boundaries.
The page never competes with them for room.

**The lookup is asked before anything is read.** Candidates are narrowed first
and only the winners are fetched -- reading every entry to choose forty is the
one thing this file must not do.

**Matching decides the order, and the budget decides who is cut.** An entry the
task shares no word with used to be dropped; the room it would have taken went
unused, which helped nobody. It is shown last instead, and only when there is
room. Sharing a word is evidence, not admission -- **scope** is admission, and
that is the author saying who an entry is for.

Design: docs/memory.md
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..layout import layout_for
from .entries import Entry, entry_of, keeps_memory, open_memory, read_page, words
from .index import narrow

# Budget for the learned entries that follow the page. Cut on whole-entry
# boundaries, best first -- half a lesson is worse than none.
ENTRIES_BUDGET = 4_000
# An entry anchored where the task works beats any merely-similar one.
_ANCHOR_BOOST = 1_000
# How many entries association spreads from. A neighbour's claim is its seed's
# divided by the seed's rank, so the hundredth-ranked entry contributes a
# hundredth of a claim to something that is ranked after every direct hit
# anyway. Bounding it also bounds the question asked of the database: naming
# every matched entry at once is a statement with one variable per entry, and
# past a few thousand SQLite refuses it -- which reached the run as an
# exception, from the one place that promised never to.
_ASSOCIATION_SEEDS = 64

# How far the walk that fills leftover room will read before giving up. The
# budget usually stops it long first; this is the floor under a project whose
# newest entries all belong to other cards.
_SCAN_CAP = 500

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


class _Where:
    """Where this task works, and where paths written in an entry point.

    Comparing scopes and anchors means resolving paths, and resolving one is a
    syscall. Neither the task's folder nor the project root moves while a recall
    runs, so both are asked for once and every entry compares against the
    answer -- asking per entry cost a syscall per entry, which was most of what
    recall spent at any size worth measuring.
    """

    def __init__(self, task: Any, project_dir: Path):
        self.folder = task.folder_path()  # None for a task that works on no folder
        self.slug = task.slug
        self.root = layout_for(project_dir).root
        self._named: dict[str, Path] = {}

    def named(self, relative: str) -> Path:
        """A path written in an entry, resolved. Entries repeat each other's
        scopes and anchors constantly, so the answer is kept."""
        found = self._named.get(relative)
        if found is None:
            found = self._named[relative] = (self.root / relative).resolve()
        return found

    def in_scope(self, entry: Entry) -> bool:
        """A filter over one store, never a wall: the word that means everyone,
        the task's own name, or a path that covers where it works."""
        for named in entry.matter.scope:
            if named in ("global", self.slug):
                return True
            base = self.named(named)
            if self.folder is not None and (self.folder == base or self.folder.is_relative_to(base)):
                return True
        return False

    def anchors(self, entry: Entry) -> bool:
        """Anchor paths are written relative to the project -- the folder the
        `poieo.yaml` sits in, which is also where the memory does."""
        if self.folder is None:
            return False  # a task that works on no folder is covered by no anchor
        for anchor in entry.matter.anchors:
            target = self.named(anchor.split("::", 1)[0])
            if target == self.folder or target.is_relative_to(self.folder) or self.folder.is_relative_to(target):
                return True
        return False


# Names per statement. Comfortably under every SQLite build's ceiling, and the
# caller never notices there was more than one.
_PER_QUERY = 400


def _fetch(con: sqlite3.Connection, slugs: list[str]) -> list[Entry]:
    found: list[Entry] = []
    for at in range(0, len(slugs), _PER_QUERY):
        batch = slugs[at : at + _PER_QUERY]
        holes = ",".join("?" * len(batch))
        found += [entry_of(row) for row in con.execute(f"SELECT * FROM entries WHERE slug IN ({holes})", batch)]
    return found


def _pool(con: sqlite3.Connection, seed: set[str], use_index: bool, allowed: "Callable[[Entry], bool]") -> list[Entry]:
    """The entries worth scoring, fetched and no more.

    Three things get fetched, and nothing else. What the lookup matched, because
    those have evidence. Anything **anchored**, because an anchored entry is
    relevant by where it points rather than by the words it shares. And enough
    of the rest, newest first, to fill the budget -- so leftover room can go to
    an entry the task happens to share no word with.

    "Enough" counts only what this task could actually be shown: filling against
    the raw row count would stop at forty entries scoped to other cards and
    leave the room empty anyway. `_SCAN_CAP` bounds the walk regardless, so a
    project whose newest thousand entries all belong elsewhere costs a bounded
    read rather than a full one.
    """
    hits = narrow(con, seed) if use_index else None
    if hits is None:
        return [entry_of(row) for row in con.execute("SELECT * FROM entries").fetchall()]
    found = [entry_of(row) for row in con.execute("SELECT * FROM entries WHERE anchors != '[]'")]
    found += _fetch(con, sorted(hits - {entry.slug for entry in found}))

    spent = sum(len(entry.body) for entry in found if allowed(entry))
    if spent >= ENTRIES_BUDGET:
        return found
    taken = {entry.slug for entry in found}
    seen = 0
    for row in con.execute("SELECT * FROM entries ORDER BY updated_at DESC, slug"):
        if spent >= ENTRIES_BUDGET or seen >= _SCAN_CAP:
            break
        seen += 1
        if row["slug"] in taken:
            continue
        entry = entry_of(row)
        found.append(entry)
        if allowed(entry):
            spent += len(entry.body)
    return found


def _neighbours(con: sqlite3.Connection, slugs: set[str]) -> list[Entry]:
    """Entries one link away from any of these, in either direction.

    Fetched by name through the link table rather than found by reading every
    entry -- association is why the memory is a graph, and it must not be the
    reason the whole graph is loaded.
    """
    if not slugs:
        return []
    names = sorted(slugs)
    reached: set[str] = set()
    for at in range(0, len(names), _PER_QUERY // 2):
        batch = names[at : at + _PER_QUERY // 2]
        holes = ",".join("?" * len(batch))
        reached |= {
            row["other"]
            for row in con.execute(
                f"SELECT target AS other FROM links WHERE slug IN ({holes})"
                "   AND kind IN ('mentions', 'depends_on')"
                f" UNION SELECT slug AS other FROM links WHERE target IN ({holes})"
                "   AND kind = 'mentions'",
                batch + batch,
            )
        }
    return _fetch(con, sorted(reached - slugs))


def recall(project_dir: Path, task: Any, use_index: bool = True) -> list[Entry]:
    """The entries this task earned, ranked, in budget. Never the page's room."""
    if not keeps_memory(project_dir):
        return []
    seed = words(f"{task.name} {task.prompt or ''} {task.folder}")

    where = _Where(task, project_dir)

    def in_scope(entry: Entry) -> bool:
        return entry.matter.superseded_by is None and where.in_scope(entry)

    def allowed(entries: list[Entry]) -> list[Entry]:
        return [entry for entry in entries if in_scope(entry)]

    from ..strength import STRONG_FLOOR, strengths

    strength = strengths(project_dir)

    with open_memory(project_dir) as con:
        candidates = allowed(_pool(con, seed, use_index, in_scope))
        if not candidates:
            return []

        scored = []
        # Entries the task matches nothing in. They wait behind everything with
        # evidence, and behind everything association reached -- and they seed
        # no associations of their own, because a claim divided by rank has to
        # start from a claim.
        spare = []
        for entry in candidates:
            score = len(seed & words(entry.body))
            if where.anchors(entry):
                score += _ANCHOR_BOOST
            (scored if score > 0 else spare).append((score, entry))
        scored.sort(key=lambda pair: (-pair[0], pair[1].slug))
        spare.sort(key=lambda pair: (-pair[1].updated_at.timestamp(), pair[1].slug))

        # Association after evidence: a neighbour's claim is its seed's,
        # divided by rank and scaled by how strong the connection is. Scope and
        # set-aside hold through connections; a second hop needs a strong
        # connection, so with nothing reinforced one hop means one hop.
        sequence = [entry for _, entry in scored]
        taken = {entry.slug for entry in sequence}
        by_slug = {entry.slug: entry for entry in sequence}

        seeds = {entry.slug for entry in sequence[:_ASSOCIATION_SEEDS]}
        first = allowed(_neighbours(con, seeds))
        by_slug |= {entry.slug: entry for entry in first}

        carry: dict[str, float] = {}
        for rank, (_, entry) in enumerate(scored[:_ASSOCIATION_SEEDS]):
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
    # A disagreement is a veto, and room does not overrule it: putting an entry
    # and the one that disputes it in front of a model together is the thing
    # `contradicts` exists to prevent, whether it arrives by a connection or by
    # there being space for it. Both directions, and against what filling has
    # already let in -- two entries disputing each other must not both arrive
    # just because they arrived together.
    for _, entry in spare:
        here = {shown.slug for shown in sequence}
        # Association may already have brought this one in. Arriving by two
        # routes is not two lessons: shown twice it reads as emphasis and
        # spends the budget twice for one thing said once.
        if entry.slug in here:
            continue
        disputed = {slug for shown in sequence for slug in shown.matter.links.contradicts}
        if entry.slug in disputed or set(entry.matter.links.contradicts) & here:
            continue
        sequence.append(entry)

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
