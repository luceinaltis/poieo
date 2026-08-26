"""Where everything a project keeps actually lives.

One module answers "what lives where", so every path in poieo is spelled in
exactly one place. Before this, ``.poieo`` appeared as a literal in seven
modules, each assembling its own idea of where a project begins -- and they
had already drifted: the run logs followed the config's ``store:``, the
memory hardcoded the tasks folder, and ``poieo eject`` guessed at the tasks
folder's parent. Three answers to one question is two too many.

**A project is the folder holding a ``poieo.yaml``. Without one, the folder
you pointed at stands in.** That single rule is what the three used to
disagree about.

What hangs off the root, and what it is worth:

- ``memory/shortterm``, ``memory/longterm`` -- what a person reads and edits,
  versioned with git.
- ``memory/cache`` -- derived from the above and rebuilt without being asked.
  Delete it and lose nothing.
- ``runs/`` -- what happened. ``store:`` moves this, and only this.
- ``worktrees/`` -- each flow's private checkout. A copy of a repository is
  not a run log, however much it is written during one, so it stays home
  when the logs are pointed elsewhere.

Nothing here touches the disk. Asking where a thing would live is not the
same as making it, and the callers that write are the ones that create.
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
        """Where one task remembers what it just did. Named for the task, so
        the pairing survives living in a different folder from the card."""
        return self.shortterm() / f"{slug}.md"

    def longterm(self) -> Path:
        """The one folder whose existence means "this project keeps a long
        memory". It must be something a person made on purpose -- which is
        why the journals sit beside it rather than inside it."""
        return self.memory() / "longterm"

    def constitution(self) -> Path:
        return self.longterm() / "constitution.md"

    def facts(self) -> Path:
        return self.longterm() / "facts"

    def attic(self) -> Path:
        return self.longterm() / "attic"

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
        """The stream, as it happens."""
        return self.runs() / "events"

    def results(self) -> Path:
        """What is left when it is over. Shares a run id with the events, and
        travels with them: a learning pass that could read one but not the
        other would be worse than one that could read neither."""
        return self.runs() / "results"

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

    The marker is parsed, not merely found: ``store:`` is part of the answer,
    and a caller that knew the root but not that key would write a run's
    events and its result to two different folders.

    A marker that cannot be parsed still raises, as it does everywhere else
    it is consulted. Callers for whom a path is worth less than the work in
    hand -- recording a run, say -- are the ones that catch.
    """
    marker = find_project_file(start)
    if marker is None:
        here = Path(start) if start is not None else Path.cwd()
        return Layout(root=here.resolve())
    # Late: project.py imports this module for Layout, and asking it to parse
    # is the only thing here that needs to know poieo.yaml has a schema.
    from .project import load_project

    return load_project(marker).layout()
