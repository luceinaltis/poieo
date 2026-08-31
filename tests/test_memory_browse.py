"""The web memory view reads the truth without inventing connections."""

from conftest import remember

from poieo.memory import index as memory_index
from poieo.memory import start_memory
from poieo.memory.browse import entry_document, graph_snapshot, keyword_search
from poieo.strength import reinforce


def _memory(tmp_path):
    start_memory(tmp_path)
    remember(
        tmp_path,
        "windows-shell",
        "Windows에서는 POSIX 셸을 우선 사용한다. [[command-env]]",
        writer="person",
    )
    remember(
        tmp_path,
        "command-env",
        "환경 변수는 명령 문자열이 아니라 별도 데이터로 전달한다.",
        writer="person",
    )
    remember(
        tmp_path,
        "search-tool",
        "파일 검색 테스트가 셸 방언과 분리되어야 한다.",
        writer="person",
    )
    remember(
        tmp_path,
        "old-shell",
        "예전 셸 규칙.",
        writer="person",
    )
    # Rewriting through the one door records both the dependency and the
    # disagreement in the derived links table.
    remember(
        tmp_path,
        "windows-shell",
        "---\nlinks:\n  depends_on: [command-env]\n  contradicts: [old-shell]\n---\n"
        "Windows에서는 POSIX 셸을 우선 사용한다. [[command-env]]",
        writer="person",
    )
    remember(
        tmp_path,
        "old-shell",
        "---\nsuperseded_by: windows-shell\n---\n예전 셸 규칙.",
        writer="person",
    )
    reinforce(tmp_path, [("windows-shell", "command-env")])


def test_graph_contains_only_connections_the_memory_declares(tmp_path):
    _memory(tmp_path)

    graph = graph_snapshot(tmp_path)

    assert graph["total_nodes"] == 4
    assert graph["total_edges"] == 4
    assert graph["truncated"] is False
    assert graph["edges_truncated"] is False
    assert {node["slug"] for node in graph["nodes"]} == {
        "windows-shell",
        "command-env",
        "search-tool",
        "old-shell",
    }
    edges = {(edge["source"], edge["target"], edge["kind"]) for edge in graph["edges"]}
    assert ("windows-shell", "command-env", "mentions") in edges
    assert ("windows-shell", "command-env", "depends_on") in edges
    assert ("old-shell", "windows-shell", "supersedes") in edges
    assert ("old-shell", "windows-shell", "contradicts") in edges
    assert all(edge["kind"] != "similar" for edge in graph["edges"])
    assert next(edge for edge in graph["edges"] if edge["kind"] == "mentions")["strength"] > 0


def test_graph_marks_set_aside_entries_without_hiding_them(tmp_path):
    _memory(tmp_path)

    nodes = {node["slug"]: node for node in graph_snapshot(tmp_path)["nodes"]}

    assert nodes["old-shell"]["standing"] is False
    assert nodes["old-shell"]["superseded_by"] == "windows-shell"
    assert nodes["windows-shell"]["standing"] is True


def test_keyword_search_finds_korean_prefixes_and_returns_no_fake_edges(tmp_path):
    _memory(tmp_path)

    results = keyword_search(tmp_path, "테스트", limit=10)

    assert [row["slug"] for row in results] == ["search-tool"]
    assert results[0]["mode"] == "words"
    assert "테스트가" in results[0]["preview"]


def test_word_scan_keeps_the_fts_any_word_semantics(tmp_path, monkeypatch):
    _memory(tmp_path)
    monkeypatch.setattr(memory_index, "ensure_lookup", lambda con: False)

    results = keyword_search(tmp_path, "없는말 테스트")

    assert [row["slug"] for row in results] == ["search-tool"]


def test_keyword_search_can_leave_past_memory_out(tmp_path):
    _memory(tmp_path)

    assert [row["slug"] for row in keyword_search(tmp_path, "예전", include_set_aside=True)] == ["old-shell"]
    assert keyword_search(tmp_path, "예전", include_set_aside=False) == []


def test_past_memory_never_leads_the_same_word_match(tmp_path):
    _memory(tmp_path)

    found = keyword_search(tmp_path, "셸")
    slugs = [row["slug"] for row in found]
    assert slugs.index("old-shell") > slugs.index("windows-shell")
    assert keyword_search(tmp_path, "예전")[0]["standing"] is False


def test_a_large_graph_says_when_it_was_capped(tmp_path):
    start_memory(tmp_path)
    for index in range(8):
        remember(tmp_path, f"note-{index}", f"memory number {index}")

    graph = graph_snapshot(tmp_path, limit=3)

    assert len(graph["nodes"]) == 3
    assert graph["total_nodes"] == 8
    assert graph["truncated"] is True


def test_a_tiny_cap_keeps_a_standing_memory_before_its_past(tmp_path):
    start_memory(tmp_path)
    remember(tmp_path, "current", "Current rule.")
    remember(tmp_path, "past", "---\nsuperseded_by: current\n---\nPast rule.")

    graph = graph_snapshot(tmp_path, limit=1)

    assert [node["slug"] for node in graph["nodes"]] == ["current"]


def test_connections_are_bounded_separately_from_memories(tmp_path):
    _memory(tmp_path)

    graph = graph_snapshot(tmp_path, edge_limit=2)

    assert len(graph["edges"]) == 2
    assert graph["total_edges"] == 4
    assert graph["edges_truncated"] is True
    assert {edge["kind"] for edge in graph["edges"]} == {"contradicts", "supersedes"}


def test_entry_detail_keeps_second_look_context_from_the_whole_memory(tmp_path):
    start_memory(tmp_path)
    remember(tmp_path, "new-rule", "Current rule.")
    remember(tmp_path, "old-rule", "---\nsuperseded_by: new-rule\n---\nOld rule.")
    remember(
        tmp_path,
        "dependent",
        "---\nlinks:\n  depends_on: [old-rule]\n---\nStill leans on the old rule.",
    )

    document = entry_document(tmp_path, "dependent")

    assert document is not None
    assert document["second_look"] == ["dependent leans on old-rule, which is set aside"]
