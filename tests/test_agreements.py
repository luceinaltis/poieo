"""The rules this repository writes about itself, held by something.

`AGENTS.md` opens by saying nothing on GitHub blocks any of it. Most of what
follows needs judgement and stays that way. A few do not: a line count, a link,
an index entry. Those are here, because a rule nobody checks is a rule that is
true until the day somebody looks.

What this cannot check is whether a document still *describes* the code. That is
merge condition 5, it is the one that matters most, and it is still a person's.

Design: docs/contribution.md
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SKIP = {".claude", ".git", "node_modules", "archive", "worktrees", "dist"}

LINK = re.compile(r"\[[^\]]*\]\(([^)#]+?)(?:#[^)]*)?\)")
DESIGN = re.compile(r"^Design:\s*(\S+)", re.M)
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def _markdown() -> list[Path]:
    return [p for p in ROOT.rglob("*.md") if not SKIP & set(p.relative_to(ROOT).parts) and "examples" not in p.parts]


def test_the_agreements_stay_under_two_hundred_lines():
    """AGENTS.md says so about itself, and is loaded whole every session.

    It grew 127 -> 257 in its first week with nothing ever cut, which is why the
    limit was written down. Counting by hand caught two overruns in one day and
    would eventually not.
    """
    lines = len((ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines())
    assert lines < 200, f"AGENTS.md is {lines} lines; say in the PR what you cut"


@pytest.mark.parametrize("doc", _markdown(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_link_points_at_something(doc: Path):
    """A doc that points at a moved file is worse than one that says nothing."""
    broken = [
        target
        for target in LINK.findall(doc.read_text(encoding="utf-8"))
        if not target.startswith(("http://", "https://", "mailto:")) and not (doc.parent / target).exists()
    ]
    assert not broken, f"{doc.relative_to(ROOT)} points at {broken}"


def test_every_component_document_is_in_the_index():
    """`docs/README.md` is the index, and an unlisted document is not found."""
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    missing = sorted(p.name for p in DOCS.glob("*.md") if p.name != "README.md" and p.name not in index)
    assert not missing, f"docs/README.md does not mention {missing}"


def test_the_index_names_the_code_each_document_covers():
    """The table's third column is how a reader gets from doc to module."""
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*\[[^\]]+\]\([^)]+\)\s*\|[^|]*\|([^|]*)\|", index, re.M)
    assert rows, "the component table lost its shape"
    gone = [
        item
        for row in rows
        for item in re.findall(r"`([^`]+)`", row)
        if not (ROOT / "src" / "poieo" / item.rstrip("/")).exists() and not (ROOT / item.rstrip("/")).exists()
    ]
    assert not gone, f"docs/README.md names code that is not there: {gone}"


def test_every_module_points_at_a_design_document_that_exists():
    """Fourteen modules end their docstring with one; it is the only thread
    tying a file to the document that must change when the file's shape does."""
    dangling = [
        (p.relative_to(ROOT), target)
        for p in (ROOT / "src").rglob("*.py")
        for target in DESIGN.findall(p.read_text(encoding="utf-8"))
        if not (ROOT / target).exists()
    ]
    assert not dangling, f"Design: pointers with nothing behind them: {dangling}"


def test_no_dated_file_outside_the_archive():
    """`docs/archive/` is history and closed. A design belongs in the component
    document it describes, and a new dated file is how that rule gets lost."""
    dated = [p.relative_to(ROOT) for p in DOCS.rglob("*.md") if DATED.match(p.name) and "archive" not in p.parts]
    assert not dated, f"dated files belong in docs/archive/, and nothing new does: {dated}"
