"""The derived index over the entry files.

Never the truth: built from the entry files, checked against them by
fingerprint, rebuilt without being asked when missing, stale, or corrupt.
Deleting it loses nothing. Any trouble here degrades to reading the files,
never to a failed run.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from functools import lru_cache
from pathlib import Path

from ..layout import Layout
from .facts import Fact

log = logging.getLogger("poieo.memory")


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
        log.info("this Python build has no FTS5; memory lookup reads the files instead")
        return False


def candidates(project_dir: Path, facts: list[Fact], seed: set[str]) -> list[Fact]:
    """Who is worth scoring. The index narrows when it can; the final ranking
    is the same plain arithmetic either way, which is what makes the slower
    path the same feature."""
    if not seed or not fts_available():
        return facts
    try:
        con = _open_index(project_dir, facts)
        try:
            rows = con.execute(
                "SELECT slug FROM facts_fts WHERE facts_fts MATCH ?",
                (" OR ".join(sorted(seed)),),
            ).fetchall()
        finally:
            con.close()
        hits = {row[0] for row in rows}
        return [fact for fact in facts if fact.slug in hits]
    except (sqlite3.Error, OSError) as exc:
        log.warning("memory index unavailable (%s); reading the files instead", exc)
        return facts


def _fingerprint(facts: list[Fact]) -> str:
    parts = sorted(f"{fact.path.name}:{fact.path.stat().st_mtime_ns}" for fact in facts)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _open_index(project_dir: Path, facts: list[Fact]) -> sqlite3.Connection:
    path = Layout(root=Path(project_dir)).index()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = _fingerprint(facts)
    con = sqlite3.connect(path, timeout=5)
    try:
        row = con.execute("SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
        if row and row[0] == stamp:
            return con
    except sqlite3.Error:
        pass  # missing tables, or not even a database: rebuild below
    try:
        _rebuild(con, facts, stamp)
        return con
    except sqlite3.Error:
        con.close()
        path.unlink(missing_ok=True)
        con = sqlite3.connect(path, timeout=5)
        _rebuild(con, facts, stamp)
        return con


def _rebuild(con: sqlite3.Connection, facts: list[Fact], stamp: str) -> None:
    con.executescript(
        "DROP TABLE IF EXISTS facts_fts;"
        "DROP TABLE IF EXISTS meta;"
        "CREATE VIRTUAL TABLE facts_fts USING fts5(slug UNINDEXED, body);"
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
    )
    con.executemany(
        "INSERT INTO facts_fts(slug, body) VALUES(?, ?)",
        [(fact.slug, fact.body) for fact in facts],
    )
    con.execute("INSERT INTO meta VALUES('fingerprint', ?)", (stamp,))
    con.commit()
