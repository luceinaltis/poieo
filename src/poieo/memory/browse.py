"""Read-only shapes for the memory view and its word search.

The graph contains only relationships a memory explicitly declares.  Search
scores may highlight nodes; they never become links.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..strength import strengths
from .entries import Entry, entry_named, history_of, keeps_memory, open_memory, readable_entries
from .index import search_text
from .upkeep import doubts

GRAPH_LIMIT = 2_000
EDGE_LIMIT = 12_000
PREVIEW_CHARS = 220


def _preview(body: str) -> str:
    compact = " ".join(body.split())
    if len(compact) <= PREVIEW_CHARS:
        return compact
    return compact[: PREVIEW_CHARS - 1].rstrip() + "…"


def _rank(entry: Entry, degree: Counter[str], uncertain: set[str]) -> tuple[Any, ...]:
    return (
        entry.slug in uncertain,
        degree[entry.slug],
        entry.updated_at,
        entry.slug,
    )


def _chosen(
    entries: list[Entry],
    degree: Counter[str],
    uncertain: set[str],
    limit: int,
) -> list[Entry]:
    if len(entries) <= limit:
        return entries
    standing = sorted(
        (entry for entry in entries if entry.matter.superseded_by is None),
        key=lambda entry: _rank(entry, degree, uncertain),
        reverse=True,
    )
    past = sorted(
        (entry for entry in entries if entry.matter.superseded_by is not None),
        key=lambda entry: _rank(entry, degree, uncertain),
        reverse=True,
    )
    # Keep a small outer shadow of past memory even when the active graph is
    # enormous.  If one side has fewer rows, the other fills the free room.
    room_after_one_standing = max(0, limit - 1) if standing else limit
    past_room = min(len(past), max(1, limit // 10), room_after_one_standing) if past else 0
    selected = standing[: max(0, limit - past_room)] + past[:past_room]
    if len(selected) < limit:
        used = {entry.slug for entry in selected}
        rest = sorted(
            (entry for entry in entries if entry.slug not in used),
            key=lambda entry: _rank(entry, degree, uncertain),
            reverse=True,
        )
        selected.extend(rest[: limit - len(selected)])
    return sorted(selected, key=lambda entry: entry.slug)


def graph_snapshot(
    project_dir: Path,
    *,
    limit: int = GRAPH_LIMIT,
    edge_limit: int = EDGE_LIMIT,
) -> dict[str, Any]:
    """A bounded graph for one paint of the memory view."""
    entries = readable_entries(project_dir)
    by_slug = {entry.slug: entry for entry in entries}
    uncertain: dict[str, list[str]] = defaultdict(list)
    for slug, reason in doubts(project_dir, entries):
        uncertain[slug].append(reason)

    raw_edges: set[tuple[str, str, str]] = set()
    for entry in entries:
        for target in entry.mentions:
            if target in by_slug and target != entry.slug:
                raw_edges.add((entry.slug, target, "mentions"))
        for target in entry.matter.links.depends_on:
            if target in by_slug and target != entry.slug:
                raw_edges.add((entry.slug, target, "depends_on"))
        for target in entry.matter.links.contradicts:
            if target in by_slug and target != entry.slug:
                one, other = sorted((entry.slug, target))
                raw_edges.add((one, other, "contradicts"))
        target = entry.matter.superseded_by
        if target in by_slug and target != entry.slug:
            raw_edges.add((entry.slug, target, "supersedes"))

    degree: Counter[str] = Counter()
    for source, target, _ in raw_edges:
        degree[source] += 1
        degree[target] += 1
    selected = _chosen(entries, degree, set(uncertain), max(1, limit))
    selected_slugs = {entry.slug for entry in selected}
    weights = strengths(project_dir)

    nodes = [
        {
            "slug": entry.slug,
            "preview": _preview(entry.body),
            "updated_at": entry.updated_at.isoformat(),
            "scope": list(entry.matter.scope),
            "anchors": list(entry.matter.anchors),
            "standing": entry.matter.superseded_by is None,
            "superseded_by": entry.matter.superseded_by,
            "second_look": uncertain.get(entry.slug, []),
            "degree": degree[entry.slug],
        }
        for entry in selected
    ]
    candidate_edges = [
        {
            "source": source,
            "target": target,
            "kind": kind,
            "strength": round(weights.get(frozenset((source, target)), 0.0), 6),
        }
        for source, target, kind in sorted(raw_edges)
        if source in selected_slugs and target in selected_slugs
    ]
    edge_priority = {"contradicts": 0, "supersedes": 1, "depends_on": 2, "mentions": 3}
    edge_limit = max(0, edge_limit)
    edges_truncated = len(candidate_edges) > edge_limit
    if edges_truncated:
        candidate_edges.sort(
            key=lambda edge: (
                edge_priority[edge["kind"]],
                -edge["strength"],
                edge["source"],
                edge["target"],
            )
        )
        candidate_edges = candidate_edges[:edge_limit]
    edges = sorted(candidate_edges, key=lambda edge: (edge["source"], edge["target"], edge["kind"]))
    return {
        "nodes": nodes,
        "edges": edges,
        "total_nodes": len(entries),
        "total_edges": len(raw_edges),
        "truncated": len(entries) > len(selected),
        "edges_truncated": edges_truncated,
    }


def keyword_search(
    project_dir: Path,
    query: str,
    *,
    limit: int = 20,
    include_set_aside: bool = True,
) -> list[dict[str, Any]]:
    """Word matches for the reader; never used by autonomous recall."""
    if not keeps_memory(project_dir):
        return []
    with open_memory(project_dir) as con:
        slugs = search_text(
            con,
            query,
            limit=limit,
            include_set_aside=include_set_aside,
        )
        if not slugs:
            return []
        placeholders = ",".join("?" for _ in slugs)
        rows = {
            row["slug"]: row
            for row in con.execute(
                f"SELECT slug, body, superseded_by, updated_at FROM entries WHERE slug IN ({placeholders})",
                slugs,
            ).fetchall()
        }
    return [
        {
            "slug": slug,
            "preview": _preview(str(rows[slug]["body"])),
            "updated_at": str(rows[slug]["updated_at"]),
            "standing": rows[slug]["superseded_by"] is None,
            "mode": "words",
            "rank": rank + 1,
        }
        for rank, slug in enumerate(slugs)
        if slug in rows
    ]


def entry_document(project_dir: Path, slug: str) -> dict[str, Any] | None:
    """One complete entry for the evidence pane."""
    entry = entry_named(project_dir, slug)
    if entry is None:
        return None
    return {
        "slug": entry.slug,
        "body": entry.body,
        "updated_at": entry.updated_at.isoformat(),
        "mentions": list(entry.mentions),
        "scope": list(entry.matter.scope),
        "anchors": list(entry.matter.anchors),
        "source": list(entry.matter.source),
        "valid_from": entry.matter.valid_from.isoformat() if entry.matter.valid_from else None,
        "superseded_by": entry.matter.superseded_by,
        "links": {
            "depends_on": list(entry.matter.links.depends_on),
            "contradicts": list(entry.matter.links.contradicts),
        },
        "second_look": [reason for named, reason in doubts(project_dir) if named == slug],
        "history": history_of(project_dir, slug),
    }
