"""Meaning search is derived, model-specific, and never memory topology."""

from conftest import remember

from poieo.memory import start_memory
from poieo.memory.semantic import semantic_search


class Embeddings:
    def __init__(self):
        self.calls: list[list[str]] = []

    async def embed(self, model, texts):
        assert model == "embed"
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            folded = text.casefold()
            if "windows" in folded or "shell" in folded or "셸" in folded:
                vectors.append([1.0, 0.0, 0.0])
            elif "database" in folded or "sqlite" in folded:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


async def test_semantic_search_orders_by_cosine_similarity(tmp_path):
    start_memory(tmp_path)
    remember(tmp_path, "windows-shell", "Windows uses a POSIX shell.")
    remember(tmp_path, "database", "SQLite stores the durable memory.")
    provider = Embeddings()

    results = await semantic_search(
        tmp_path,
        "셸 실행 환경",
        provider=provider,
        model="embed",
        model_key="local/embed@one",
    )

    assert [row["slug"] for row in results] == ["windows-shell", "database"]
    assert results[0]["score"] > results[1]["score"]
    assert all(row["mode"] == "meaning" for row in results)


async def test_entry_vectors_are_cached_but_queries_are_not(tmp_path):
    start_memory(tmp_path)
    remember(tmp_path, "windows-shell", "Windows uses a POSIX shell.")
    remember(tmp_path, "database", "SQLite stores the durable memory.")
    provider = Embeddings()

    await semantic_search(
        tmp_path,
        "shell",
        provider=provider,
        model="embed",
        model_key="local/embed@one",
    )
    await semantic_search(
        tmp_path,
        "database",
        provider=provider,
        model="embed",
        model_key="local/embed@one",
    )

    # First query, the two missing documents, then the second query.  No
    # document batch the second time: the cache is the derived work saved.
    assert provider.calls == [
        ["shell"],
        [
            "database\nSQLite stores the durable memory.",
            "windows-shell\nWindows uses a POSIX shell.",
        ],
        ["database"],
    ]
    assert (tmp_path / "memory" / "cache" / "embeddings.sqlite3").is_file()


async def test_editing_one_entry_invalidates_only_its_vector(tmp_path):
    start_memory(tmp_path)
    remember(tmp_path, "windows-shell", "Windows uses a POSIX shell.")
    remember(tmp_path, "database", "SQLite stores the durable memory.")
    provider = Embeddings()
    kwargs = {
        "provider": provider,
        "model": "embed",
        "model_key": "local/embed@one",
    }

    await semantic_search(tmp_path, "shell", **kwargs)
    remember(tmp_path, "database", "SQLite is the one durable database.")
    await semantic_search(tmp_path, "shell", **kwargs)

    assert provider.calls[-1] == ["database\nSQLite is the one durable database."]
