"""The derived lookup over the pieces.

Never the truth: built from the ``pieces`` table beside it, maintained by
triggers, and safe to drop and rebuild at any moment. Trouble here degrades to
reading every piece, never to a failed run -- which is also what happens on a
Python whose SQLite was compiled without FTS5.

Design: docs/memory.md
"""

from __future__ import annotations

import logging
import sqlite3
from functools import lru_cache

log = logging.getLogger("poieo.memory")

_LOOKUP = """
CREATE VIRTUAL TABLE pieces_fts USING fts5(text, content='pieces', content_rowid='id');
INSERT INTO pieces_fts(rowid, text) SELECT id, text FROM pieces;
CREATE TRIGGER pieces_after_insert AFTER INSERT ON pieces BEGIN
    INSERT INTO pieces_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER pieces_after_delete AFTER DELETE ON pieces BEGIN
    INSERT INTO pieces_fts(pieces_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER pieces_after_update AFTER UPDATE ON pieces BEGIN
    INSERT INTO pieces_fts(pieces_fts, rowid, text) VALUES('delete', old.id, old.text);
    INSERT INTO pieces_fts(rowid, text) VALUES (new.id, new.text);
END;
"""


@lru_cache(maxsize=None)
def fts_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE probe USING fts5(body)")
        finally:
            con.close()
        return True
    except sqlite3.Error:
        log.info("this Python build has no FTS5; memory lookup reads every piece instead")
        return False


def ensure_lookup(con: sqlite3.Connection) -> bool:
    """Build the lookup if this build can and it is not there yet.

    Called on every open, which is what lets a database made on a Python
    without FTS5 gain the lookup the first time it is opened on one with it.
    """
    if not fts_available():
        return False
    try:
        have = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'pieces_fts'").fetchone()
        if have is None:
            con.executescript(_LOOKUP)
            con.commit()
        return True
    except sqlite3.Error as exc:
        log.warning("could not build the memory lookup (%s); reading every piece instead", exc)
        return False


def narrow(con: sqlite3.Connection, seed: set[str]) -> set[str] | None:
    """Slugs worth scoring, or None when everything is.

    None is not an error -- it is the honest answer when there is no lookup to
    ask, and the caller then scores every piece by the same arithmetic. The
    ranking is the same either way, which is what keeps the slower path the
    same feature rather than a second one.
    """
    if not seed or not ensure_lookup(con):
        return None
    try:
        rows = con.execute(
            "SELECT DISTINCT p.slug FROM pieces_fts f JOIN pieces p ON p.id = f.rowid WHERE pieces_fts MATCH ?",
            (" OR ".join(sorted(seed)),),
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("memory lookup unavailable (%s); reading every piece instead", exc)
        return None
    return {row[0] for row in rows}
