"""Where everything a project keeps actually lives.

Every path in poieo is spelled here and nowhere else.

**A project is the folder holding a ``poieo.yaml``. Without one, the folder
you pointed at stands in.**

Nothing here touches the disk: asking where a thing would live is not the same
as making it, and the callers that write are the ones that create.

Design: docs/storage.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MARKER = "poieo.yaml"


@dataclass(frozen=True)
class Layout:
    """The paths one project stands for."""

    root: Path
    # Where the run history goes, when the project says somewhere else.
    # None means the ordinary place, under the root.
    runs_override: Path | None = None

    # -- the memory a person reads and edits (git) ---------------------------
    def memory(self) -> Path:
        return self.root / "memory"

    def shortterm(self) -> Path:
        return self.memory() / "shortterm"

    def journal(self, slug: str) -> Path:
        # Named for the task, so the pairing survives the journal living in a
        # different folder from the card.
        return self.shortterm() / f"{slug}.md"

    def longterm(self) -> Path:
        """The folder whose existence means "this project keeps a long memory".

        It must be something a person made on purpose, which is why the
        journals sit beside it rather than inside it -- those arrive on their
        own, the first time a task runs.
        """
        return self.memory() / "longterm"

    def constitution(self) -> Path:
        return self.longterm() / "constitution.md"

    def facts(self) -> Path:
        # Named for the folder on disk, which stays `facts/`; the things in it
        # are Entries everywhere else.
        return self.longterm() / "facts"

    # -- the memory only the machine reads (derived) -------------------------
    def cache(self) -> Path:
        return self.memory() / "cache"

    def blobs(self) -> Path:
        return self.cache() / "blobs"

    def index(self) -> Path:
        return self.cache() / "index.sqlite3"

    def strength(self) -> Path:
        return self.cache() / "strength.json"

    def learning_log(self) -> Path:
        return self.cache() / "learning.jsonl"

    # -- what a run leaves behind --------------------------------------------
    def runs(self) -> Path:
        return self.runs_override or self.root / "runs"

    def run_index(self) -> Path:
        return self.runs() / "index.jsonl"

    def events(self) -> Path:
        return self.runs() / "events"

    def results(self) -> Path:
        # Under runs(), not memory(): a result must travel with the events of
        # the same run, or a learning pass can read one and not the other.
        return self.runs() / "results"

    def asking(self) -> Path:
        # Under runs(), because a question is the tail of one run and lives as
        # long as it does. Gitignored with the rest of runs/: losing one costs
        # a card being run again to ask it, never anybody's work.
        return self.runs() / "asking"

    def worktrees(self) -> Path:
        return self.root / "worktrees"


def find_project_file(start: str | Path | None = None) -> Path | None:
    """The nearest ``poieo.yaml`` at or above ``start`` (default: cwd)."""
    here = Path(start) if start is not None else Path.cwd()
    here = here.resolve()
    for candidate in (here, *here.parents):
        marker = candidate / MARKER
        if marker.is_file():
            return marker
    return None


def layout_for(start: str | Path | None = None) -> Layout:
    """Where the project containing ``start`` keeps things.

    The marker is parsed, not merely found, because ``store:`` is part of the
    answer. Raises if it will not parse; callers for whom a path is worth less
    than the work in hand -- recording a run, say -- are the ones that catch.
    """
    marker = find_project_file(start)
    if marker is None:
        here = Path(start) if start is not None else Path.cwd()
        return Layout(root=here.resolve())
    from .project import load_project  # late: project.py imports this module

    return load_project(marker).layout()
