"""Choosing what a task is shown, and assembling the block it reads.

The page comes first and whole, so the stable part of the prompt stays stable;
the entries the task earned follow it, best first, on whole-entry boundaries.
The page never competes with them for room.

**The lookup is asked before anything is read, and ranking reads less than an
entry.** Candidates are narrowed first, ranked from the few columns ranking
actually needs, and only what will be shown is read in full -- parsing fifty
thousand entries to choose forty is the one thing this file must not do.

**Matching decides the order, and the budget decides who is cut.** An entry the
task shares no word with used to be dropped; the room it would have taken went
unused, which helped nobody. It is shown last instead, and only when there is
room. Sharing a word is evidence, not admission -- **scope** is admission, and
that is the author saying who an entry is for.

Design: docs/memory.md
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..layout import layout_for
from .entries import Entry, entry_of, keeps_memory, open_memory, read_page, words
from .index import narrow
from .judgements import judgement

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

    def in_scope(self, scope: str) -> bool:
        """A filter over one store, never a wall.

        Takes the column as it is stored. Almost every entry is for everyone,
        and that answer costs a string comparison instead of a parse.
        """
        return True if scope == _EVERYONE else self.covers(json.loads(scope))

    def covers(self, scope: "list[str]") -> bool:
        """The same question of a scope already in hand: the word that means
        everyone, the task's own name, or a path that covers where it works."""
        for named in scope:
            if named in ("global", self.slug):
                return True
            base = self.named(named)
            if self.folder is not None and (self.folder == base or self.folder.is_relative_to(base)):
                return True
        return False

    def anchors(self, raw: str) -> bool:
        """Anchor paths are written relative to the project -- the folder the
        `poieo.yaml` sits in, which is also where the memory does.

        Most entries anchor nothing, and the column says so without being read.
        """
        if self.folder is None:
            return False  # a task that works on no folder is covered by no anchor
        for anchor in _tuple(raw):
            target = self.named(anchor.split("::", 1)[0])
            if target == self.folder or target.is_relative_to(self.folder) or self.folder.is_relative_to(target):
                return True
        return False


# Names per statement. Comfortably under every SQLite build's ceiling, and the
# caller never notices there was more than one.
_PER_QUERY = 400


# The ordinary scope, as it sits in the column. Comparing the stored text
# against this answers "is this for everyone?" without parsing anything, which
# is the answer for almost every entry there is.
_EVERYONE = json.dumps(["global"])


@dataclass(frozen=True)
class _Ranked:
    """An entry as **ranking** sees it: enough to score, order and cut by, and
    not one field more.

    Recall showed about forty entries out of however many matched, and built
    every one of them first -- six JSON columns parsed and three models
    validated each, then discarded. What decides the answer is the shape it is
    matched by, its size, its scope, whether it anchors, and what it disputes;
    all of that is a column, and most of it needs no parsing at all.
    """

    slug: str
    score: int
    size: int
    at: str
    contradicts: tuple[str, ...]


def _tuple(raw: str) -> tuple[str, ...]:
    """A JSON list column, parsed only when it holds something."""
    return () if raw in ("[]", "", None) else tuple(json.loads(raw))


def _fetch(con: sqlite3.Connection, slugs: list[str]) -> list[Entry]:
    found: list[Entry] = []
    for at in range(0, len(slugs), _PER_QUERY):
        batch = slugs[at : at + _PER_QUERY]
        holes = ",".join("?" * len(batch))
        found += [entry_of(row) for row in con.execute(f"SELECT * FROM entries WHERE slug IN ({holes})", batch)]
    return found


# The columns ranking needs. `length(body)` rather than the body: the budget is
# decided in characters, and the characters themselves are only wanted for the
# entries that survive it.
_RANKING = (
    "SELECT e.slug, e.scope, e.anchors, e.contradicts, e.superseded_by,"
    "       e.updated_at AS at, length(e.body) AS size, p.shape"
    "  FROM entries e JOIN pieces p ON p.slug = e.slug AND p.ord = 0"
)


def _rank(con: sqlite3.Connection, seed: set[str], use_index: bool, where: "_Where") -> list[_Ranked]:
    """Everything worth scoring, scored, without reading an entry.

    Three things are considered, and nothing else. What the lookup matched,
    because those have evidence. Anything **anchored**, because an anchored
    entry is relevant by where it points rather than by the words it shares. And
    enough of the rest, newest first, to fill the budget -- so leftover room can
    go to an entry the task happens to share no word with.

    "Enough" counts only what this task could actually be shown: filling against
    the raw row count would stop at forty entries scoped to other cards and
    leave the room empty anyway. `_SCAN_CAP` bounds the walk regardless, so a
    project whose newest thousand entries all belong elsewhere costs a bounded
    read rather than a full one.
    """
    hits = narrow(con, seed) if use_index else None

    def rank(row: "sqlite3.Row") -> "_Ranked | None":
        if row["superseded_by"] is not None or not where.in_scope(row["scope"]):
            return None
        score = len(seed & set(row["shape"].split()))
        if where.anchors(row["anchors"]):
            score += _ANCHOR_BOOST
        return _Ranked(row["slug"], score, row["size"], row["at"], _tuple(row["contradicts"]))

    if hits is None:
        return [found for row in con.execute(_RANKING) if (found := rank(row)) is not None]

    ranked: list[_Ranked] = []
    seen: set[str] = set()
    for row in con.execute(f"{_RANKING} WHERE e.anchors != '[]'"):
        seen.add(row["slug"])
        if (found := rank(row)) is not None:
            ranked.append(found)
    # Sorted once. Sorting inside the loop re-sorted the whole match set for
    # every batch of four hundred, which at fifty thousand was most of what
    # ranking cost.
    outstanding = sorted(hits - seen)
    for at in range(0, len(outstanding), _PER_QUERY):
        batch = outstanding[at : at + _PER_QUERY]
        holes = ",".join("?" * len(batch))
        for row in con.execute(f"{_RANKING} WHERE e.slug IN ({holes})", batch):
            seen.add(row["slug"])
            if (found := rank(row)) is not None:
                ranked.append(found)

    spent = sum(found.size for found in ranked)
    if spent >= ENTRIES_BUDGET:
        return ranked
    walked = 0
    for row in con.execute(f"{_RANKING} ORDER BY e.updated_at DESC, e.slug"):
        if spent >= ENTRIES_BUDGET or walked >= _SCAN_CAP:
            break
        walked += 1
        if row["slug"] in seen:
            continue
        seen.add(row["slug"])
        found = rank(row)
        if found is not None:
            ranked.append(found)
            spent += found.size
    return ranked


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


def recall(project_dir: Path, task: Any, use_index: bool = True, judge: bool = True) -> list[Entry]:
    """The entries this task earned, ranked, in budget. Never the page's room.

    ``judge`` applies a verdict a learning pass has left for this card over
    exactly this candidate set -- which of them a model said actually apply --
    and is off only for the pass that is about to write one.
    """
    if not keeps_memory(project_dir):
        return []
    seed = words(f"{task.name} {task.prompt or ''} {task.folder}")
    where = _Where(task, project_dir)

    from ..strength import STRONG_FLOOR, strengths

    strength = strengths(project_dir)

    with open_memory(project_dir) as con:
        ranked = _rank(con, seed, use_index, where)
        if not ranked:
            return []

        # Entries the task matches nothing in. They wait behind everything with
        # evidence, and behind everything association reached -- and they seed
        # no associations of their own, because a claim divided by rank has to
        # start from a claim.
        scored = sorted((r for r in ranked if r.score > 0), key=lambda r: (-r.score, r.slug))
        # Newest first, and by name within a moment -- two sorts because one
        # `reverse` would turn the names round with the clock.
        spare = sorted((r for r in ranked if r.score == 0), key=lambda r: r.slug)
        spare.sort(key=lambda r: r.at, reverse=True)

        # Association needs what an entry *says* -- its mentions and its typed
        # links -- so here, and only here, entries are read in full. The seeds
        # are the strongest handful and their neighbours are however many the
        # link table names, so this is bounded by neither the memory's size nor
        # the budget.
        seeds = [found.slug for found in scored[:_ASSOCIATION_SEEDS]]
        told = {entry.slug: entry for entry in _fetch(con, seeds)}
        # Everything with evidence, not only the seeds: a neighbour that is
        # already ranked on its own words is not reached, it is already here.
        taken = {found.slug for found in scored}
        allowed = {found.slug for found in ranked}
        first = [e for e in _neighbours(con, set(seeds)) if e.slug in allowed or _also(where, e)]

        carry: dict[str, float] = {}
        for rank, slug in enumerate(seeds):
            entry = told.get(slug)
            if entry is None:
                continue
            for neighbor in connected(entry, first):
                if neighbor.slug in taken:
                    continue
                weight = strength.get(frozenset((slug, neighbor.slug)), 0.0)
                carry[neighbor.slug] = carry.get(neighbor.slug, 0.0) + (1.0 + weight) / (1 + rank)

        by_slug = {entry.slug: entry for entry in first}
        second = [e for e in _neighbours(con, set(carry)) if e.slug in allowed or _also(where, e)]
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

        # One ordered list of names, and their sizes, before a single body has
        # been read: what the lookup scored, what association reached, then what
        # is left while there is room.
        order: list[tuple[str, int, tuple[str, ...]]] = [(r.slug, r.size, r.contradicts) for r in scored]
        placed = {slug for slug, _, _ in order}
        for slug in sorted(carry, key=lambda s: (-carry[s], s)):
            entry = by_slug[slug]
            if slug not in placed:
                order.append((slug, len(entry.body), tuple(entry.matter.links.contradicts)))
                placed.add(slug)
        # A disagreement is a veto, and room does not overrule it: putting an
        # entry and the one that disputes it in front of a model together is the
        # thing `contradicts` exists to prevent, whether it arrives by a
        # connection or by there being space for it. Arriving by two routes is
        # not two lessons either -- shown twice it spends the budget twice for
        # one thing said once.
        for found in spare:
            if found.slug in placed:
                continue
            here = {slug for slug, _, _ in order}
            disputed = {other for _, _, says in order for other in says}
            if found.slug in disputed or set(found.contradicts) & here:
                continue
            order.append((found.slug, found.size, found.contradicts))
            placed.add(found.slug)

        # One entry too big for the budget loses its own place, not everybody
        # else's: the room it could not use goes to whoever ranks below it.
        chosen: list[str] = []
        spent = 0
        for slug, size, _ in order:
            if spent + size > ENTRIES_BUDGET:
                continue
            chosen.append(slug)
            spent += size

        # And now, at last, the bodies -- of the ones that will be read.
        have = {slug: entry for slug, entry in told.items()} | by_slug
        missing = [slug for slug in chosen if slug not in have]
        have |= {entry.slug: entry for entry in _fetch(con, missing)}
    shown = [have[slug] for slug in chosen if slug in have]
    if not judge:
        return shown
    # A verdict left for this card over exactly these candidates drops what a
    # judge said does not apply. No verdict, no filtering: the block is what it
    # always was, and a run never waits for one.
    keep = judgement(project_dir, task, shown)
    return shown if keep is None else [entry for entry in shown if entry.slug in keep]


def _also(where: "_Where", entry: Entry) -> bool:
    """Whether a neighbour the ranking never saw is one this task may see.

    Association reaches entries the lookup did not match, so their scope has not
    been asked about yet. Asked of the entry, because association is the one
    place that already holds the whole thing.
    """
    return entry.matter.superseded_by is None and where.covers(entry.matter.scope)


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
