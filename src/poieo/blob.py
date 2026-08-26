"""Kept copies of the bytes an entry was written against.

Point, don't remember: the entry's words stay the memory, and the exact
content they were written about is kept here, under its own digest, where
it can be opened when detail matters. A keepsake is a copy, never a
meaning -- losing one costs a precise comparison and an openable original,
not a word of what was learned -- so nothing in this module is ever worth
raising over.

The store is flat and content-addressed: same content, same name, one
copy; written via tmp+rename, so a torn write cannot leave a wrong body
under a right name.

Spec: docs/specs/2026-08-24-keepsakes-design.md
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

log = logging.getLogger("poieo.memory")

STORE = "blobs"
# Files past this are not kept: hoarding is an anti-goal, and so is a
# night's work failing over a fat file.
KEEP_CAP = 8 * 1024 * 1024


def digest(path: Path) -> str | None:
    """The content's name, streamed; None on any trouble."""
    try:
        parts = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                parts.update(chunk)
        return parts.hexdigest()
    except OSError:
        return None


def keep(project_dir: Path, path: Path) -> str | None:
    """Copy the file into the store and return its name, or None -- over
    the cap, unreadable, unwritable -- with the reason logged."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > KEEP_CAP:
            if path.is_file():
                log.info("not keeping %s: over the size cap", path)
            return None
        # One read both names and fills the keepsake: hashing and copying
        # from two reads would let a file changing between them leave wrong
        # bytes under a right name.
        data = path.read_bytes()
        if len(data) > KEEP_CAP:
            # It grew past the cap between the stat and the read.
            log.info("not keeping %s: over the size cap", path)
            return None
        name = hashlib.sha256(data).hexdigest()
        store = Path(project_dir) / ".poieo" / STORE
        target = store / name
        if target.exists():
            return name
        store.mkdir(parents=True, exist_ok=True)
        temp = store / f".{name}.tmp"
        temp.write_bytes(data)
        os.replace(temp, target)
        return name
    except OSError as exc:
        log.warning("could not keep %s: %s", path, exc)
        return None


def kept(project_dir: Path, name: str) -> Path | None:
    """Where the keepsake lives, or None if it is gone."""
    target = Path(project_dir) / ".poieo" / STORE / name
    return target if target.is_file() else None
