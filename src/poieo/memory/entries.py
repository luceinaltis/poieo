"""The files the memory is made of: the page, and one entry per thing learned.

Truth lives here, in markdown under git, under ``memory/longterm/``.
Everything a machine derives from these files lives one folder over, in
``memory/cache/``, and can be deleted without loss.

Design: docs/memory.md
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..errors import SpecError, describe_invalid
from ..layout import layout_for

log = logging.getLogger("poieo.memory")

# Advisory budget (~3k tokens) for the always-present page: the page is the
# user's to trim, and refusing to run over it would make the memory a way to
# break the daemon.
PAGE_BUDGET = 12_000

# One shared "the" must not make an entry relevant to everything.
_GLUE = frozenset(
    "a an and are as at be but by for from if in is it no not of on or so "
    "that the this to was were will with you".split()
)


def words(text: str) -> set[str]:
    """An entry's distinctive words. The vocabulary both retrieval and the
    accounting judge by, so they cannot disagree about what an entry says."""
    return set(re.findall(r"[a-z0-9_]+", text.lower())) - _GLUE


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
    # Anchor path -> digest of the content the entry was written against.
    # The bytes live under memory/cache/blobs/, never here.
    sealed: dict[str, str] = Field(default_factory=dict)


class Entry(BaseModel):
    """One learned entry: a slug, a body, and its frontmatter."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    slug: str
    body: str
    matter: _Frontmatter
    path: Path
    # [[names]] in the body: untyped, free to dangle -- a mention of an
    # entry that does not exist yet marks something worth writing.
    mentions: list[str] = Field(default_factory=list)


def keeps_memory(project_dir: Path) -> bool:
    """Whether this project keeps a long memory. The folder is the whole opt-in.

    ``memory/longterm/`` and not ``memory/``, because journals live under
    ``memory/`` too and arrive on their own the first time a task runs -- a
    signal that switches itself on is not consent.
    """
    return layout_for(project_dir).longterm().is_dir()


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


def load_entry(path: Path) -> Entry:
    """One entry file, parsed and validated. Raises SpecError on a typo."""
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
    return Entry(slug=path.stem, body=body, matter=parsed, path=path, mentions=mentions)


def load_entries(project_dir: Path) -> list[Entry]:
    """Every learned entry, in a stable order. Malformed ones raise, so the
    caller decides whether that is a load failure or a 3am shrug."""
    root = layout_for(project_dir).facts()
    if not root.is_dir():
        return []
    return [load_entry(p) for p in sorted(root.glob("*.md"))]


def readable_entries(project_dir: Path) -> list[Entry]:
    """Every entry that still reads, for the run path. A malformed one is a
    load failure when loading (check_memory); mid-residency it is skipped --
    a run with less in mind beats no run at all."""
    root = layout_for(project_dir).facts()
    if not root.is_dir():
        return []
    entries = []
    for path in sorted(root.glob("*.md")):
        try:
            entries.append(load_entry(path))
        except SpecError as exc:
            log.warning("%s; leaving it out of this run", exc)
    return entries


def check_memory(project_dir: Path) -> None:
    """Fail at launch, not at 3am: a typo in the memory must surface where
    `poieo validate` and the daemon's load can see it.

    Typed claims only -- prose ``[[mentions]]`` are deliberately free to
    dangle, since one naming an entry that does not exist marks something worth
    writing.
    """
    entries = load_entries(project_dir)
    known = {entry.slug for entry in entries}
    attic = layout_for(project_dir).attic()
    if attic.is_dir():
        # Resting entries still exist, or "move the file back" would not be
        # true. A genuine typo names something that exists nowhere and fails.
        known |= {path.stem for path in attic.glob("*.md")}
    for entry in entries:
        claims = [
            ("depends_on", target) for target in entry.matter.links.depends_on
        ] + [("contradicts", target) for target in entry.matter.links.contradicts]
        if entry.matter.superseded_by is not None:
            claims.append(("superseded_by", entry.matter.superseded_by))
        for kind, target in claims:
            if target not in known:
                raise SpecError(
                    f"{entry.path}: {kind} names '{target}', and no such entry exists"
                )
        anchored = {anchor.split("::", 1)[0] for anchor in entry.matter.anchors}
        for path in entry.matter.sealed:
            if path not in anchored:
                raise SpecError(
                    f"{entry.path}: sealed names '{path}', which is not an anchor here"
                )


def read_page(project_dir: Path) -> str | None:
    """The always-present page as text, or None when the project keeps none."""
    path = layout_for(project_dir).constitution()
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
