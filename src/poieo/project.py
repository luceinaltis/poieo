"""A folder is a project when it holds a ``poieo.yaml``.

Discovery walks from a starting directory upward and stops at the first
marker, the way git finds ``.git``. Commands use it to fill flags the user
left silent -- the flag always wins, and discovery only fills silence, so a
folder with no marker behaves exactly as it always has.
"""

from __future__ import annotations

from pathlib import Path

from .daemon.config import DaemonConfig, load_config

MARKER = "poieo.yaml"


def find_project_file(start: str | Path | None = None) -> Path | None:
    """The nearest ``poieo.yaml`` at or above ``start`` (default: cwd)."""
    here = Path(start) if start is not None else Path.cwd()
    here = here.resolve()
    for candidate in (here, *here.parents):
        marker = candidate / MARKER
        if marker.is_file():
            return marker
    return None


def find_project(start: str | Path | None = None) -> DaemonConfig | None:
    """The loaded config of the nearest project, or None outside one.

    A marker that fails to load raises the same ``SpecError`` an explicit
    ``poieo daemon poieo.yaml`` would -- a broken project file should fail
    loudly wherever it is consulted, not be silently skipped over.
    """
    marker = find_project_file(start)
    return load_config(marker) if marker else None
