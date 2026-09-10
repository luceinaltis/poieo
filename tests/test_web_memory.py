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
        "page_text": "",
        "suggestion": None,
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
        "learning": [],
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


# -- a person's writes, from the board ---------------------------------------


def _suggested(root, line="Require ISO dates."):
    import json

    from conftest import at

    at(root).cache().mkdir(parents=True, exist_ok=True)
    at(root).learning_log().write_text(
        json.dumps({"at": "2026-08-20T00:00:00+00:00", "read": 1, "upto": "a", "error": None, "page": line}) + "\n",
        encoding="utf-8",
    )


def _page_written_long_ago(root):
    import sqlite3

    from conftest import at

    con = sqlite3.connect(at(root).longterm())
    con.execute("UPDATE page SET updated_at = '2026-08-01T00:00:00+00:00'")
    con.commit()
    con.close()


def test_the_overview_carries_the_page_as_written_and_the_last_suggestion(tmp_path):
    from poieo.memory import write_page

    client = _client(tmp_path)
    write_page(tmp_path, "<!-- trim me -->\nKeep tests portable.")
    _page_written_long_ago(tmp_path)
    _suggested(tmp_path)

    body = client.get("/api/projects/board/memory").json()
    assert body["page"] == "Keep tests portable."
    assert body["page_text"] == "<!-- trim me -->\nKeep tests portable."
    assert body["suggestion"] == "Require ISO dates."


def test_a_person_writes_the_page_from_the_board(tmp_path):
    from poieo.memory import history_of, read_page

    client = _client(tmp_path)
    before = client.get("/api/projects/board/memory").headers["etag"]

    response = client.put("/api/projects/board/memory/page", json={"text": "Dates are ISO."})

    assert response.status_code == 200
    assert read_page(tmp_path) == "Dates are ISO."
    assert history_of(tmp_path)[0]["writer"] == "person"
    assert client.get("/api/projects/board/memory").headers["etag"] != before
    assert client.put("/api/projects/board/memory/page", json={"text": 3}).status_code == 400


def test_a_suggestion_lands_or_is_let_go_from_the_board(tmp_path):
    from poieo.memory import read_page, write_page

    client = _client(tmp_path)
    write_page(tmp_path, "Keep tests portable.")
    _page_written_long_ago(tmp_path)
    _suggested(tmp_path)

    landed = client.post("/api/projects/board/memory/suggestion", json={"accept": True})
    assert landed.status_code == 200
    assert landed.json()["suggestion"] == "Require ISO dates."
    assert read_page(tmp_path) == "Keep tests portable.\nRequire ISO dates."
    assert client.get("/api/projects/board/memory").json()["suggestion"] is None

    _suggested(tmp_path, "Another line.")
    _page_written_long_ago(tmp_path)
    assert client.get("/api/projects/board/memory").json()["suggestion"] == "Another line."
    gone = client.post("/api/projects/board/memory/suggestion", json={"accept": False})
    assert gone.status_code == 200
    assert read_page(tmp_path) == "Keep tests portable.\nRequire ISO dates."
    assert client.get("/api/projects/board/memory").json()["suggestion"] is None
    assert client.post("/api/projects/board/memory/suggestion", json={"accept": False}).status_code == 409
    assert client.post("/api/projects/board/memory/suggestion", json={"accept": "yes"}).status_code == 400


def test_a_person_keeps_an_entry_from_the_board(tmp_path):
    from poieo.memory import entry_named

    client = _client(tmp_path)
    response = client.put(
        "/api/projects/board/memory/feeds-order",
        json={"body": "Feeds are imported oldest first.", "links": {"depends_on": ["command-env"]}},
    )

    assert response.status_code == 200
    entry = entry_named(tmp_path, "feeds-order")
    assert entry.body == "Feeds are imported oldest first."
    assert entry.matter.links.depends_on == ["command-env"]
    assert entry.matter.source == []
    assert client.get("/api/projects/board/memory/feeds-order").json()["history"][0]["writer"] == "person"

    dangling = client.put(
        "/api/projects/board/memory/leaner",
        json={"body": "Leans on air.", "links": {"depends_on": ["ghost"]}},
    )
    assert dangling.status_code == 409
    assert "ghost" in dangling.json()["error"]
    assert entry_named(tmp_path, "leaner") is None
    assert client.put("/api/projects/board/memory/Bad Name", json={"body": "x"}).status_code == 400
    assert client.put("/api/projects/board/memory/empty", json={"body": "  "}).status_code == 400
    assert (
        client.put("/api/projects/board/memory/typo", json={"body": "x", "links": {"caused_by": []}}).status_code == 400
    )
    # What only the harness may stamp cannot arrive from a page.
    stamped = client.put("/api/projects/board/memory/stamped", json={"body": "x", "source": ["run-1"]})
    assert stamped.status_code == 200
    assert entry_named(tmp_path, "stamped").matter.source == []


def test_a_person_sets_an_entry_aside_from_the_board(tmp_path):
    from poieo.memory import entry_named

    client = _client(tmp_path)
    response = client.post("/api/projects/board/memory/windows-shell/set-aside", json={"because": "command-env"})

    assert response.status_code == 200
    assert entry_named(tmp_path, "windows-shell").matter.superseded_by == "command-env"
    assert (
        client.post("/api/projects/board/memory/nobody/set-aside", json={"because": "command-env"}).status_code == 404
    )
    ghost = client.post("/api/projects/board/memory/command-env/set-aside", json={"because": "ghost"})
    assert ghost.status_code == 409
    assert client.post("/api/projects/board/memory/command-env/set-aside", json={}).status_code == 400
    assert entry_named(tmp_path, "command-env").matter.superseded_by is None


def test_memory_writes_need_a_memory_and_the_same_fence_as_every_write(tmp_path):
    client = _client(tmp_path, memory=False)
    assert client.put("/api/projects/board/memory/page", json={"text": "x"}).status_code == 409
    assert client.put("/api/projects/board/memory/slug", json={"body": "x"}).status_code == 409
    assert client.post("/api/projects/board/memory/slug/set-aside", json={"because": "y"}).status_code == 409
    assert client.post("/api/projects/board/memory/suggestion", json={"accept": True}).status_code == 409

    elsewhere = {"origin": "https://elsewhere.example", "host": "127.0.0.1:8484"}
    kept = tmp_path / "kept"
    kept.mkdir()
    fenced = _client(kept)
    assert fenced.put("/api/projects/board/memory/page", json={"text": "x"}, headers=elsewhere).status_code == 403
    assert fenced.put("/api/projects/board/memory/slug", json={"body": "x"}, headers=elsewhere).status_code == 403


# -- a run and the memory it was shown, in both directions --------------------


def _record(tmp_path, run_id, *, task="importer", shown=None, summary="nothing tonight", status="completed"):
    import json

    from conftest import at

    folder = at(tmp_path).results()
    folder.mkdir(parents=True, exist_ok=True)
    record = {"run_id": run_id, "task": task, "status": status, "summary": summary, "outputs": {}}
    if shown is not None:
        record["shown"] = shown
    (folder / f"{run_id}.json").write_text(json.dumps(record), encoding="utf-8")


def test_a_run_says_which_memory_it_was_shown_and_which_it_used(tmp_path):
    client = _client(tmp_path)
    _record(
        tmp_path,
        "20260824T010000-aaaaaaaa",
        shown=["windows-shell", "command-env", "long-gone"],
        summary="Windows 테스트에서는 POSIX 셸을 우선한다고 정리했다",
    )

    response = client.get("/api/runs/20260824T010000-aaaaaaaa/memory")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "20260824T010000-aaaaaaaa",
        "task": "importer",
        "shown": [
            {"slug": "windows-shell", "used": True},
            {"slug": "command-env", "used": False},
            # An entry the memory no longer holds cannot be judged.
            {"slug": "long-gone", "used": None},
        ],
    }


def test_a_run_recorded_without_memory_answers_null_not_an_empty_list(tmp_path):
    client = _client(tmp_path)
    _record(tmp_path, "20260824T010000-aaaaaaaa")

    body = client.get("/api/runs/20260824T010000-aaaaaaaa/memory").json()

    assert body["shown"] is None and body["task"] == "importer"


def test_a_run_nobody_recorded_is_404(tmp_path):
    assert _client(tmp_path).get("/api/runs/nope/memory").status_code == 404


def test_an_entry_names_the_task_behind_each_source_run(tmp_path):
    client = _client(tmp_path)
    _record(tmp_path, "20260824T010000-aaaaaaaa", task="importer")
    remember(
        tmp_path,
        "learned-cap",
        "---\nsource: ['20260824T010000-aaaaaaaa', '20260824T020000-bbbbbbbb']\n---\nThe api caps at 50.",
    )

    body = client.get("/api/projects/board/memory/learned-cap").json()

    assert body["source"] == ["20260824T010000-aaaaaaaa", "20260824T020000-bbbbbbbb"]
    assert body["sources"] == [
        {"run_id": "20260824T010000-aaaaaaaa", "task": "importer"},
        # The record is gone (runs/ is disposable), so there is nowhere to go.
        {"run_id": "20260824T020000-bbbbbbbb", "task": None},
    ]


def test_the_overview_carries_recent_passes_and_a_new_pass_moves_the_revision(tmp_path):
    import json

    from conftest import at

    client = _client(tmp_path)
    first = client.get("/api/projects/board/memory")
    assert first.json()["learning"] == []

    log = at(tmp_path).learning_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        json.dumps(
            {
                "at": "2026-08-21T03:00:00+00:00",
                "read": 2,
                "upto": "b",
                "kept": ["windows-shell"],
                "set_aside": [],
                "dropped": ["'bad slug': not a plain slug"],
                "error": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    response = client.get("/api/projects/board/memory", headers={"if-none-match": first.headers["etag"]})

    assert response.status_code == 200
    assert response.headers["etag"] != first.headers["etag"]
    passes = response.json()["learning"]
    assert passes[0]["kept"] == ["windows-shell"]
    assert passes[0]["dropped"] == ["'bad slug': not a plain slug"]
