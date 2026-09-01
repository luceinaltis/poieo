"""The derived lookup over the pieces.

Never the truth: built from the ``pieces`` table beside it, maintained by
triggers, and safe to drop and rebuild at any moment. Trouble here degrades to
reading every piece, never to a failed run -- which is also what happens on a
Python whose SQLite was compiled without FTS5.

Design: docs/memory.md
"""

from __future__ import annotations

import logging
import re
import sqlite3
from functools import lru_cache

log = logging.getLogger("poieo.memory")

# Built over `pieces.shape`, never `pieces.text`: the words a task asks with
# are shaped before they get here, and matching shapes against raw words would
# find an entry in one direction and not the other.
_LOOKUP = """
CREATE VIRTUAL TABLE pieces_fts USING fts5(shape, content='pieces', content_rowid='id');
INSERT INTO pieces_fts(rowid, shape) SELECT id, shape FROM pieces;
CREATE TRIGGER pieces_after_insert AFTER INSERT ON pieces BEGIN
    INSERT INTO pieces_fts(rowid, shape) VALUES (new.id, new.shape);
END;
CREATE TRIGGER pieces_after_delete AFTER DELETE ON pieces BEGIN
    INSERT INTO pieces_fts(pieces_fts, rowid, shape) VALUES('delete', old.id, old.shape);
END;
CREATE TRIGGER pieces_after_update AFTER UPDATE ON pieces BEGIN
    INSERT INTO pieces_fts(pieces_fts, rowid, shape) VALUES('delete', old.id, old.shape);
    INSERT INTO pieces_fts(rowid, shape) VALUES (new.id, new.shape);
END;
"""

# A reader searches the words as they were written, not the ASCII-only shapes
# autonomous recall deliberately uses.  This is a second derived index so a
# Korean search can improve without changing which memories reach a run.
_TEXT_LOOKUP = """
CREATE VIRTUAL TABLE pieces_text_fts USING fts5(
    text,
    content='pieces',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
INSERT INTO pieces_text_fts(rowid, text) SELECT id, text FROM pieces;
CREATE TRIGGER pieces_text_after_insert AFTER INSERT ON pieces BEGIN
    INSERT INTO pieces_text_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER pieces_text_after_delete AFTER DELETE ON pieces BEGIN
    INSERT INTO pieces_text_fts(pieces_text_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER pieces_text_after_update AFTER UPDATE ON pieces BEGIN
    INSERT INTO pieces_text_fts(pieces_text_fts, rowid, text) VALUES('delete', old.id, old.text);
    INSERT INTO pieces_text_fts(rowid, text) VALUES (new.id, new.text);
END;
"""

_TRIGGERS = ("pieces_after_insert", "pieces_after_delete", "pieces_after_update")
_TEXT_TRIGGERS = (
    "pieces_text_after_insert",
    "pieces_text_after_delete",
    "pieces_text_after_update",
)


def drop_lookup(con: sqlite3.Connection) -> None:
    """Take the lookup away so the next open rebuilds it. Safe at any time:
    it is derived, and a memory with no lookup reads every piece instead."""
    for trigger in (*_TRIGGERS, *_TEXT_TRIGGERS):
        con.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    con.execute("DROP TABLE IF EXISTS pieces_fts")
    con.execute("DROP TABLE IF EXISTS pieces_text_fts")


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
        have_shapes = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'pieces_fts'").fetchone()
        if have_shapes is None:
            con.executescript(_LOOKUP)
        have_text = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'pieces_text_fts'").fetchone()
        if have_text is None:
            con.executescript(_TEXT_LOOKUP)
        if have_shapes is None or have_text is None:
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


def search_text(
    con: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    include_set_aside: bool = True,
) -> list[str]:
    """Entry slugs matching the text a person typed, best first.

    Prefixes are intentional: Korean particles remain attached to a token, so
    a query for ``테스트`` must still find ``테스트가``.  If FTS is absent or
    rejects a query, the same substring rule is applied by a plain scan.
    """
    query = query.strip()
    if not query or limit <= 0:
        return []

    tokens = re.findall(r"\w+", query.casefold(), flags=re.UNICODE)
    wanted = [token.casefold() for token in tokens] or [query.casefold()]
    slug_rows = con.execute(
        "SELECT slug, superseded_by FROM entries WHERE (? OR superseded_by IS NULL)",
        (include_set_aside,),
    ).fetchall()
    slug_matches = [
        str(row[0])
        for row in sorted(
            (row for row in slug_rows if any(token in str(row[0]).casefold() for token in wanted)),
            key=lambda row: (
                row[1] is not None,
                str(row[0]).casefold() != query.casefold(),
                -sum(token in str(row[0]).casefold() for token in wanted),
                str(row[0]),
            ),
        )
    ]
    if tokens and ensure_lookup(con):
        expression = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)
        try:
            rows = con.execute(
                "SELECT p.slug FROM pieces_text_fts f "
                "JOIN pieces p ON p.id = f.rowid "
                "JOIN entries e ON e.slug = p.slug "
                "WHERE pieces_text_fts MATCH ? "
                "AND (? OR e.superseded_by IS NULL) "
                "ORDER BY (e.superseded_by IS NOT NULL), bm25(pieces_text_fts), p.slug LIMIT ?",
                (expression, include_set_aside, limit * 4),
            ).fetchall()
            answer = list(dict.fromkeys([*slug_matches, *(str(row[0]) for row in rows)]))
            if answer:
                return answer[:limit]
        except sqlite3.Error as exc:
            log.warning("memory text lookup unavailable (%s); scanning every piece instead", exc)

    # Python casefold is Unicode-aware where SQLite's built-in lower() is not.
    rows = con.execute(
        "SELECT p.slug, p.text FROM pieces p JOIN entries e ON e.slug = p.slug "
        "WHERE (? OR e.superseded_by IS NULL) "
        "ORDER BY (e.superseded_by IS NOT NULL), p.slug, p.ord",
        (include_set_aside,),
    ).fetchall()
    answer: list[str] = slug_matches[:limit]
    for row in rows:
        folded = str(row[1]).casefold()
        if any(token in folded for token in wanted) and row[0] not in answer:
            answer.append(str(row[0]))
            if len(answer) == limit:
                break
    return answer
