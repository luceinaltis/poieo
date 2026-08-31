"""Embedding search over memory entries, backed only by a disposable cache."""

from __future__ import annotations

import asyncio
import hashlib
import math
import sqlite3
from array import array
from pathlib import Path
from typing import Any

from ..errors import ProviderError
from ..layout import layout_for
from ..providers.base import Provider
from .browse import _preview
from .entries import Entry, readable_entries

_BATCH = 64
_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors(
    model_key  TEXT NOT NULL,
    slug       TEXT NOT NULL,
    digest     TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector     BLOB NOT NULL,
    PRIMARY KEY(model_key, slug)
);
"""


def _path(project_dir: Path) -> Path:
    return layout_for(project_dir).cache() / "embeddings.sqlite3"


def _text(entry: Entry) -> str:
    return f"{entry.slug}\n{entry.body}"


def _digest(entry: Entry) -> str:
    return hashlib.sha256(_text(entry).encode("utf-8")).hexdigest()


def _cached(
    project_dir: Path,
    model_key: str,
    entries: list[Entry],
) -> tuple[dict[str, list[float]], list[Entry]]:
    path = _path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=10) as con:
        con.executescript(_SCHEMA)
        rows = {
            row[0]: row
            for row in con.execute(
                "SELECT slug, digest, dimensions, vector FROM vectors WHERE model_key = ?",
                (model_key,),
            ).fetchall()
        }
    vectors: dict[str, list[float]] = {}
    missing: list[Entry] = []
    for entry in entries:
        row = rows.get(entry.slug)
        if row is None or row[1] != _digest(entry):
            missing.append(entry)
            continue
        try:
            values = array("f")
            values.frombytes(row[3])
            vector = [float(value) for value in values]
        except (TypeError, ValueError):
            missing.append(entry)
            continue
        if len(vector) != row[2] or not vector:
            missing.append(entry)
            continue
        vectors[entry.slug] = vector
    return vectors, missing


def _store(
    project_dir: Path,
    model_key: str,
    entries: list[Entry],
    vectors: list[list[float]],
) -> None:
    path = _path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=10) as con:
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO vectors(model_key, slug, digest, dimensions, vector) VALUES(?,?,?,?,?) "
            "ON CONFLICT(model_key, slug) DO UPDATE SET "
            "digest=excluded.digest, dimensions=excluded.dimensions, vector=excluded.vector",
            [
                (
                    model_key,
                    entry.slug,
                    _digest(entry),
                    len(vector),
                    array("f", vector).tobytes(),
                )
                for entry, vector in zip(entries, vectors)
            ],
        )


def _cosine(one: list[float], other: list[float]) -> float:
    if len(one) != len(other) or not one:
        return -1.0
    one_norm = math.sqrt(sum(value * value for value in one))
    other_norm = math.sqrt(sum(value * value for value in other))
    if one_norm == 0 or other_norm == 0:
        return 0.0
    return sum(left * right for left, right in zip(one, other)) / (one_norm * other_norm)


def _valid(vectors: list[list[float]], expected: int, dimensions: int) -> bool:
    return len(vectors) == expected and all(len(vector) == dimensions and vector for vector in vectors)


async def semantic_search(
    project_dir: Path,
    query: str,
    *,
    provider: Provider,
    model: str,
    model_key: str,
    limit: int = 20,
    include_set_aside: bool = True,
) -> list[dict[str, Any]]:
    """Rank entries in one embedding space; no score is ever stored as a link."""
    query = query.strip()
    if not query or limit <= 0:
        return []
    entries = await asyncio.to_thread(readable_entries, project_dir)
    if not include_set_aside:
        entries = [entry for entry in entries if entry.matter.superseded_by is None]
    if not entries:
        return []

    query_rows = await provider.embed(model, [query])
    if len(query_rows) != 1 or not query_rows[0]:
        raise ProviderError(
            f"{getattr(provider, 'name', 'embedder')}: embedding response contained no query vector",
            provider=getattr(provider, "name", None),
        )
    query_vector = query_rows[0]
    dimensions = len(query_vector)
    vectors, missing = await asyncio.to_thread(_cached, project_dir, model_key, entries)
    # A model behind an unchanged name can be replaced.  Its query dimension
    # is the current truth; cache rows from the old space are all disposable.
    if any(len(vector) != dimensions for vector in vectors.values()):
        vectors = {}
        missing = entries

    for start in range(0, len(missing), _BATCH):
        batch = missing[start : start + _BATCH]
        embedded = await provider.embed(model, [_text(entry) for entry in batch])
        if not _valid(embedded, len(batch), dimensions):
            raise ProviderError(
                f"{getattr(provider, 'name', 'embedder')}: entry embeddings do not match the query space",
                provider=getattr(provider, "name", None),
            )
        await asyncio.to_thread(_store, project_dir, model_key, batch, embedded)
        vectors.update({entry.slug: vector for entry, vector in zip(batch, embedded)})

    scored = sorted(
        ((_cosine(query_vector, vectors[entry.slug]), entry) for entry in entries if entry.slug in vectors),
        key=lambda pair: (-pair[0], pair[1].slug),
    )[: min(50, limit)]
    return [
        {
            "slug": entry.slug,
            "preview": _preview(entry.body),
            "updated_at": entry.updated_at.isoformat(),
            "standing": entry.matter.superseded_by is None,
            "mode": "meaning",
            "score": round(score, 6),
            "rank": rank + 1,
        }
        for rank, (score, entry) in enumerate(scored)
    ]
