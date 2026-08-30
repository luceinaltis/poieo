"""What the memory would like a person to look at.

Computed at read time -- no queue, no stored counter, nothing written.
**Nothing anywhere acts on any of it.**

Design: docs/memory.md
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..blob import digest, path_for
from .entries import PAGE_BUDGET, Entry, keeps_memory, read_page, readable_entries
from .index import fts_available
from .results import results_dir, used_in

# How far back the accounting reads, and how often an entry must have been
# shown, unused, before it is worth naming.
ACCOUNT_WINDOW = 50
UNUSED_FLOOR = 3


def memory_report(project_dir: Path) -> dict[str, Any] | None:
    """What `poieo memory` prints, or None when the project keeps none."""
    if not keeps_memory(project_dir):
        return None
    text = read_page(project_dir)
    entries = readable_entries(project_dir)
    standing = [entry for entry in entries if entry.matter.superseded_by is None]
    standing_slugs = {entry.slug for entry in standing}

    disagreements = sorted(
        {
            tuple(sorted((entry.slug, other)))
            for entry in standing
            for other in entry.matter.links.contradicts
            if other in standing_slugs
        }
    )
    return {
        "page_chars": len(text or ""),
        "page_budget": PAGE_BUDGET,
        "kept": len(standing),
        "set_aside": len(entries) - len(standing),
        "lookup": "fast" if fts_available() else "one piece at a time",
        "disagreements": disagreements,
        "second_look": [reason for _, reason in doubts(project_dir, entries)],
        "accounting": accounting(project_dir, entries),
    }


def accounting(project_dir: Path, entries: list[Entry]) -> dict[str, Any] | None:
    """Is the memory earning its keep? A read over the recent run records,
    never a stored counter, and nothing anywhere acts on it."""
    root = results_dir(project_dir)
    if not root.is_dir():
        return None
    by_slug = {entry.slug: entry for entry in entries}
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
            entry = by_slug.get(slug)
            if entry is not None and used_in(entry, record):
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


def _changed_since(named: Path, entry: Entry) -> bool:
    """Did the anchored file move after the entry itself last did?

    The entry's own timestamp took the place of its file's mtime, which is
    what still makes "edit the entry after looking" clear the flag."""
    return datetime.fromtimestamp(named.stat().st_mtime, timezone.utc) > entry.updated_at


def doubts(project_dir: Path, entries: list[Entry] | None = None) -> list[tuple[str, str]]:
    """Every kept entry worth a second look, with the sentence saying why.

    A lean on a set-aside entry, an anchor whose target is gone, or one that
    changed after the entry was written -- and editing the entry is how a
    person clears that last one: look, then touch.
    """
    entries = readable_entries(project_dir) if entries is None else entries
    aside = {entry.slug for entry in entries if entry.matter.superseded_by is not None}
    out: list[tuple[str, str]] = []
    for entry in entries:
        if entry.matter.superseded_by is not None:
            continue
        for target in entry.matter.links.depends_on:
            if target in aside:
                out.append((entry.slug, f"{entry.slug} leans on {target}, which is set aside"))
        for anchor in entry.matter.anchors:
            part = anchor.split("::", 1)[0]
            named = project_dir / part
            try:
                if not named.exists():
                    out.append((entry.slug, f"{entry.slug} names {anchor}, which is gone"))
                    continue
                seal = entry.matter.sealed.get(part)
                if seal is not None and path_for(project_dir, seal) is not None:
                    # Sealed: doubt by content, not clocks, so a touched-but-
                    # identical file raises nothing. The mtime check stays
                    # so revising the entry still clears the flag.
                    if digest(named) != seal and _changed_since(named, entry):
                        out.append(
                            (
                                entry.slug,
                                f"{entry.slug} names {anchor}, which no longer matches what it was written against",
                            )
                        )
                elif _changed_since(named, entry):
                    out.append(
                        (
                            entry.slug,
                            f"{entry.slug} names {anchor}, which changed after it was written",
                        )
                    )
            except OSError:
                # Unreadable is present: upkeep never turns an I/O hiccup
                # into doubt.
                pass
    return sorted(out)
