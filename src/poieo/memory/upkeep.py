"""What the memory would like a person to look at.

Everything here is computed from the files at read time -- no queue, no
stored counter, nothing written. A disagreement whose one side was set aside
is resolved and disappears; whatever leaned on that side surfaces under
second look instead. Nothing anywhere acts on any of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..blob import digest, kept
from .results import results_dir, used_in
from .facts import PAGE_BUDGET, Fact, keeps_memory, read_page, readable_facts
from .index import fts_available

# How far back the accounting reads, and how often an entry must have been
# shown, unused, before it is worth naming.
ACCOUNT_WINDOW = 50
UNUSED_FLOOR = 3


def memory_report(project_dir: Path) -> dict[str, Any] | None:
    """What `poieo memory` prints, or None when the project keeps none."""
    if not keeps_memory(project_dir):
        return None
    text = read_page(project_dir)
    facts = readable_facts(project_dir)
    standing = [fact for fact in facts if fact.matter.superseded_by is None]
    standing_slugs = {fact.slug for fact in standing}

    disagreements = sorted(
        {
            tuple(sorted((fact.slug, other)))
            for fact in standing
            for other in fact.matter.links.contradicts
            if other in standing_slugs
        }
    )
    return {
        "page_chars": len(text or ""),
        "page_budget": PAGE_BUDGET,
        "kept": len(standing),
        "set_aside": len(facts) - len(standing),
        "lookup": "fast" if fts_available() else "file-by-file",
        "disagreements": disagreements,
        "second_look": [reason for _, reason in doubts(project_dir, facts)],
        "accounting": accounting(project_dir, facts),
    }


def accounting(project_dir: Path, facts: list[Fact]) -> dict[str, Any] | None:
    """Is the memory earning its keep? A read over the recent run records,
    never a stored counter, and nothing anywhere acts on it."""
    root = results_dir(project_dir)
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
            if fact is not None and used_in(fact, record):
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
    facts = readable_facts(project_dir) if facts is None else facts
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
                    # Sealed: doubt by content, not clocks -- a touched-but-
                    # identical file raises nothing. But the clearing
                    # gesture stays the same as everywhere: a person who
                    # revised the entry after the content changed has
                    # looked, and must not be nagged until they hand-
                    # compute a digest.
                    if (
                        digest(named) != seal
                        and named.stat().st_mtime_ns > fact.path.stat().st_mtime_ns
                    ):
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
