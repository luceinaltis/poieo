"""Choosing what a task is shown, and assembling the block it reads.

The page comes first and whole, so the stable part of the prompt stays stable;
the entries the task earned follow it, best first, cut on whole-entry
boundaries. The page never competes with them for room.

Design: docs/memory.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..layout import layout_for
from .facts import Fact, read_page, readable_facts, tokens
from .index import candidates

# Budget for the learned entries that follow the page. Cut on whole-entry
# boundaries, best first -- half a lesson is worse than none.
FACTS_BUDGET = 4_000
# An entry anchored where the task works beats any merely-similar one.
_ANCHOR_BOOST = 1_000

# Interface words only past this point: the machinery names (tiers, facts,
# retrieval) stay in this package and the spec.
PAGE_HEADER = "What this project always requires:"
LEARNED_HEADER = "What earlier work here has learned:"


def read_memory(
    project_dir: Path, task: Any | None = None, *, preview: bool = False
) -> str | None:
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
        parts.append(LEARNED_HEADER + "\n\n" + "\n\n".join(fact.body for fact in chosen))
    return "\n\n".join(parts) or None


def _in_scope(fact: Fact, task: Any, project_dir: Path) -> bool:
    """A filter over one store, never a wall: the word that means everyone,
    the task's own name, or a path that covers where it works."""
    folder = task.folder_path()
    for entry in fact.matter.scope:
        if entry in ("global", task.slug):
            return True
        base = (layout_for(project_dir).root / entry).resolve()
        if folder == base or folder.is_relative_to(base):
            return True
    return False


def _anchored(fact: Fact, task: Any, project_dir: Path) -> bool:
    """Anchor paths are written relative to the project -- the folder the
    `poieo.yaml` sits in, which is also where `memory/` does."""
    folder = task.folder_path()
    for anchor in fact.matter.anchors:
        target = (layout_for(project_dir).root / anchor.split("::", 1)[0]).resolve()
        if target == folder or target.is_relative_to(folder) or folder.is_relative_to(target):
            return True
    return False


def recall(project_dir: Path, task: Any, use_index: bool = True) -> list[Fact]:
    """The entries this task earned, ranked, in budget. Never the page's room."""
    facts = [
        fact
        for fact in readable_facts(project_dir)
        if fact.matter.superseded_by is None and _in_scope(fact, task, project_dir)
    ]
    if not facts:
        return []
    seed = tokens(f"{task.name} {task.prompt or ''} {task.folder}")

    # An anchored entry is relevant by where it points, not by the words it
    # shares, so it must not depend on the index finding a shared word.
    narrowed = candidates(project_dir, facts, seed) if use_index else facts
    pool = {fact.slug: fact for fact in narrowed}
    for fact in facts:
        if _anchored(fact, task, project_dir):
            pool.setdefault(fact.slug, fact)

    scored = []
    for fact in pool.values():
        score = len(seed & tokens(fact.body))
        if _anchored(fact, task, project_dir):
            score += _ANCHOR_BOOST
        if score > 0:
            scored.append((score, fact))
    scored.sort(key=lambda pair: (-pair[0], pair[1].slug))

    # Association after evidence: a neighbour's claim is its seed's, divided by
    # rank and scaled by how worn the connection is. Drawn from the already
    # filtered pool, so scope and set-aside hold through connections; a second
    # hop needs a worn connection, so with no wear one hop means one hop.
    from ..strength import WORN_FLOOR, wear_of

    worn = wear_of(project_dir)
    sequence = [fact for _, fact in scored]
    taken = {fact.slug for fact in sequence}

    carry: dict[str, float] = {}
    for rank, (_, fact) in enumerate(scored):
        for neighbor in connected(fact, facts):
            if neighbor.slug in taken:
                continue
            wear = worn.get(frozenset((fact.slug, neighbor.slug)), 0.0)
            carry[neighbor.slug] = carry.get(neighbor.slug, 0.0) + (1.0 + wear) / (1 + rank)

    by_slug = {fact.slug: fact for fact in facts}
    further: dict[str, float] = {}
    for slug, reached in carry.items():
        for neighbor in connected(by_slug[slug], facts):
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


def connected(fact: Fact, eligible: list[Fact]) -> list[Fact]:
    """Who arrives beside this entry.

    Mentions count either way (nearness is symmetric); ``depends_on`` forward
    only (what you chose needs what it leans on, not the reverse); and
    ``contradicts`` is a **veto**, not one vote -- "this disputes [[x]]" is an
    ordinary way to write a disagreement, and the mention in it must not
    smuggle the disputed entry into a prompt.
    """
    named = set(fact.mentions) | set(fact.matter.links.depends_on)
    return sorted(
        (
            other
            for other in eligible
            if other.slug != fact.slug
            and (other.slug in named or fact.slug in other.mentions)
            and other.slug not in fact.matter.links.contradicts
            and fact.slug not in other.matter.links.contradicts
        ),
        key=lambda other: other.slug,
    )
