"""The board's read-only window onto one project's long memory."""

from conftest import remember
from starlette.testclient import TestClient

from poieo.daemon import Daemon, load_config
from poieo.memory import start_memory
from poieo.providers import LLMResponse, Usage
from poieo.providers.local import OpenAICompatibleProvider
from poieo.store import NullStore
from poieo.strength import reinforce
from poieo.web import create_app

_BINDING = """\
name: memory-board
providers:
  local: {type: openai_compatible, base_url: "http://local/v1"}
default: {provider: local, model: chat}
roles:
  memory_searcher: {provider: local, model: answerer}
  memory_embedder: {provider: local, model: embedder}
"""


def _client(tmp_path, *, memory=True, binding=_BINDING):
    (tmp_path / "models.yaml").write_text(binding, encoding="utf-8")
    (tmp_path / "cards").mkdir()
    marker = tmp_path / "poieo.yaml"
    marker.write_text(
        "name: board\ntasks: cards\nbinding: models.yaml\n",
        encoding="utf-8",
    )
    if memory:
        start_memory(tmp_path)
        remember(
            tmp_path,
            "windows-shell",
            "Windows 테스트에서는 POSIX 셸을 우선한다. [[command-env]]",
        )
        remember(
            tmp_path,
            "command-env",
            "환경 변수는 명령 문자열과 분리한다.",
        )
    daemon = Daemon(load_config(marker), store=NullStore())
    return TestClient(create_app(daemon))


def test_memory_overview_names_capabilities_and_bounded_graph(tmp_path):
    response = _client(tmp_path).get("/api/projects/board/memory")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["capabilities"] == {"words": True, "meaning": True, "ask": True}
    assert body["graph"]["total_nodes"] == 2
    assert body["graph"]["total_edges"] == 1
    assert {node["slug"] for node in body["graph"]["nodes"]} == {
        "windows-shell",
        "command-env",
    }
    assert body["stats"]["kept"] == 2


def test_an_unchanged_memory_overview_skips_the_expensive_read(tmp_path, monkeypatch):
    client = _client(tmp_path)
    first = client.get("/api/projects/board/memory")
    revision = first.headers["etag"]

    def should_not_read(*_args, **_kwargs):
        raise AssertionError("an unchanged memory should not rebuild its overview")

    monkeypatch.setattr("poieo.web.server.memory_report", should_not_read)
    monkeypatch.setattr("poieo.web.server.graph_snapshot", should_not_read)

    response = client.get(
        "/api/projects/board/memory",
        headers={"if-none-match": revision},
    )

    assert response.status_code == 304
    assert response.headers["etag"] == revision


def test_a_memory_write_changes_the_overview_revision(tmp_path):
    client = _client(tmp_path)
    first = client.get("/api/projects/board/memory")

    remember(tmp_path, "new-rule", "새로 배운 규칙이다.")
    response = client.get(
        "/api/projects/board/memory",
        headers={"if-none-match": first.headers["etag"]},
    )

    assert response.status_code == 200
    assert response.headers["etag"] != first.headers["etag"]
    assert response.json()["graph"]["total_nodes"] == 3


def test_reinforced_connections_change_the_overview_revision(tmp_path):
    client = _client(tmp_path)
    first = client.get("/api/projects/board/memory")

    reinforce(tmp_path, [("windows-shell", "command-env")])
    response = client.get(
        "/api/projects/board/memory",
        headers={"if-none-match": first.headers["etag"]},
    )

    assert response.status_code == 200
    assert response.headers["etag"] != first.headers["etag"]
    assert response.json()["graph"]["edges"][0]["strength"] > 0


def test_an_anchor_change_changes_the_overview_revision(tmp_path):
    client = _client(tmp_path)
    anchor = tmp_path / "guide.md"
    anchor.write_text("before", encoding="utf-8")
    remember(
        tmp_path,
        "anchored-rule",
        "---\nanchors: [guide.md]\n---\nThe guide is current.",
    )
    first = client.get("/api/projects/board/memory")

    anchor.write_text("after", encoding="utf-8")
    response = client.get(
        "/api/projects/board/memory",
        headers={"if-none-match": first.headers["etag"]},
    )

    assert response.status_code == 200
    assert response.headers["etag"] != first.headers["etag"]
    assert any("guide.md" in reason for reason in response.json()["stats"]["second_look"])


def test_a_project_without_memory_is_an_empty_place_not_a_failure(tmp_path):
    response = _client(tmp_path, memory=False).get("/api/projects/board/memory")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "page": None,
        "stats": None,
        "capabilities": {"words": False, "meaning": False, "ask": False},
        "graph": {
            "nodes": [],
            "edges": [],
            "total_nodes": 0,
            "total_edges": 0,
            "truncated": False,
            "edges_truncated": False,
        },
    }


def test_one_memory_entry_is_read_on_demand_with_its_history(tmp_path):
    response = _client(tmp_path).get("/api/projects/board/memory/windows-shell")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "windows-shell"
    assert "POSIX 셸" in body["body"]
    assert body["mentions"] == ["command-env"]
    assert body["history"][0]["slug"] == "windows-shell"


def test_word_search_is_unicode_aware_and_read_only(tmp_path):
    response = _client(tmp_path).post(
        "/api/projects/board/memory/search",
        json={"query": "테스트", "mode": "words", "limit": 10, "include_set_aside": True},
    )

    assert response.status_code == 200
    assert [row["slug"] for row in response.json()["results"]] == ["windows-shell"]
    assert response.json()["mode"] == "words"


def test_search_refuses_an_unknown_mode_instead_of_guessing(tmp_path):
    response = _client(tmp_path).post(
        "/api/projects/board/memory/search",
        json={"query": "shell", "mode": "magic"},
    )

    assert response.status_code == 400
    assert "mode" in response.json()["error"]


def test_model_searches_reject_unbounded_prompts(tmp_path):
    client = _client(tmp_path)

    search = client.post(
        "/api/projects/board/memory/search",
        json={"query": "x" * 2_001, "mode": "meaning"},
    )
    ask = client.post(
        "/api/projects/board/memory/ask",
        json={"question": "x" * 2_001},
    )

    assert search.status_code == 400
    assert ask.status_code == 400


def test_meaning_search_uses_the_dedicated_embedding_role(tmp_path, monkeypatch):
    asked = []

    async def fake_embed(self, model, texts):
        asked.append((model, list(texts)))
        return [[1.0, 0.0] if "Windows" in text or "테스트" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(OpenAICompatibleProvider, "embed", fake_embed)
    response = _client(tmp_path).post(
        "/api/projects/board/memory/search",
        json={"query": "테스트", "mode": "meaning", "limit": 10},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "meaning"
    assert response.json()["results"][0]["slug"] == "windows-shell"
    assert all(model == "embedder" for model, _ in asked)


def test_meaning_search_says_which_role_is_missing(tmp_path):
    binding = """\
name: no-search
providers:
  local: {type: openai_compatible, base_url: "http://local/v1"}
default: {provider: local, model: chat}
"""
    response = _client(tmp_path, binding=binding).post(
        "/api/projects/board/memory/search",
        json={"query": "테스트", "mode": "meaning"},
    )

    assert response.status_code == 409
    assert "memory_embedder" in response.json()["error"]


def test_ask_returns_an_answer_and_the_memory_it_cited(tmp_path, monkeypatch):
    asked = []

    async def fake_complete(self, request):
        asked.append(request)
        return LLMResponse(
            text="POSIX 셸이 필요합니다 [[windows-shell]].",
            model="answerer:served",
            usage=Usage(input_tokens=30, output_tokens=8),
        )

    async def fake_embed(self, model, texts):
        return [[1.0, 0.0] if "Windows" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", fake_complete)
    monkeypatch.setattr(OpenAICompatibleProvider, "embed", fake_embed)
    response = _client(tmp_path).post(
        "/api/projects/board/memory/ask",
        json={"question": "Windows 테스트가 왜 깨지나요?", "include_set_aside": True},
    )

    assert response.status_code == 200
    assert response.json()["citations"] == ["windows-shell"]
    assert response.json()["model"] == "answerer:served"
    assert response.json()["evidence"][0]["slug"] == "windows-shell"
    assert asked[0].model == "answerer"


def test_ask_never_falls_back_to_the_default_chat_model(tmp_path):
    binding = """\
name: no-answerer
providers:
  local: {type: openai_compatible, base_url: "http://local/v1"}
default: {provider: local, model: expensive-default}
roles:
  memory_embedder: {provider: local, model: embedder}
"""
    response = _client(tmp_path, binding=binding).post(
        "/api/projects/board/memory/ask",
        json={"question": "Windows"},
    )

    assert response.status_code == 409
    assert "memory_searcher" in response.json()["error"]


def test_memory_routes_keep_project_identity(tmp_path):
    response = _client(tmp_path).get("/api/projects/elsewhere/memory")

    assert response.status_code == 404
    assert response.json()["projects"] == ["board"]
