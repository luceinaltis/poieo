"""The observation API over a stub daemon."""

import asyncio
from types import SimpleNamespace

from starlette.testclient import TestClient

from test_workspace import git, head, make_repo

from poieo.binding import BindingSpec
from poieo.workspace import Workspace
from poieo.graph import GraphSpec
from poieo.store import Event, RunStore
from poieo.web.events import BroadcastStore
from poieo.web import server
from poieo.web.server import create_app, sse_frame, _event_stream


def stub_daemon(tmp_path, runners=()):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    return SimpleNamespace(runners=list(runners), store=store)


# A real GraphSpec, not a stub: the wiring the board is served comes straight
# off it, and a stub would let the shape drift from the schema unnoticed.
STUB_GRAPH = {
    "name": "support-triage",
    "entry": "classify",
    "nodes": [
        {"id": "classify", "type": "agent", "prompt": "x", "role": "classifier", "next": "route"},
        {
            "id": "route",
            "type": "router",
            "branches": [{"when": "category == 'bug'", "to": "answer", "label": "bug"}],
            "default": "answer",
        },
        {"id": "answer", "type": "agent", "prompt": "y", "ui": {"x": 40, "y": 8}},
    ],
}


# Real too, and for the same reason: the model a node reports comes straight off
# `resolve`, so a stub would let the board drift from what the run will do.
STUB_BINDING = {
    "providers": {
        "ollama": {"type": "ollama", "base_url": "http://localhost:11434"},
        "claude": {"type": "anthropic"},
    },
    "default": {"provider": "claude", "model": "claude-opus-5"},
    "roles": {"classifier": {"provider": "ollama", "model": "llama3.2:3b"}},
}


def stub_runner(
    name="triage",
    status="waiting",
    current=None,
    last=None,
    workspace=None,
    then=(),
    graph=None,
    binding=None,
):
    return SimpleNamespace(
        name=name,
        status=status,
        current_run_id=current,
        last_result=last,
        workspace=workspace,
        trigger=SimpleNamespace(describe=f"interval 30s"),
        task=SimpleNamespace(
            graph=GraphSpec.model_validate(graph or STUB_GRAPH),
            binding=BindingSpec.model_validate(binding or STUB_BINDING),
            spec=SimpleNamespace(then=list(then)),
        ),
    )


def test_flows_lists_runner_state(tmp_path):
    last = SimpleNamespace(summary=lambda: {"run_id": "r0", "status": "completed"})
    daemon = stub_daemon(tmp_path, [stub_runner(last=last)])
    client = TestClient(create_app(daemon))

    body = client.get("/api/tasks").json()
    assert body["tasks"] == [
        {
            "name": "triage",
            "graph": "support-triage",
            "trigger": "interval 30s",
            "status": "waiting",
            "current_run_id": None,
            "last_run": {"run_id": "r0", "status": "completed"},
            "pending": 0,
            "into": None,
            "then": [],
            "shape": {
                "entry": "classify",
                "nodes": [
                    {
                        "id": "classify",
                        "type": "agent",
                        "next": "route",
                        "default": None,
                        "branches": [],
                        "model": "llama3.2:3b",
                    },
                    {
                        "id": "route",
                        "type": "router",
                        "next": None,
                        "default": "answer",
                        "branches": [{"to": "answer", "label": "bug"}],
                        "model": None,
                    },
                    {
                        "id": "answer",
                        "type": "agent",
                        "next": None,
                        "default": None,
                        "branches": [],
                        "model": "claude-opus-5",
                        "ui": {"x": 40.0, "y": 8.0},
                    },
                ],
            },
        }
    ]


def test_a_flow_serves_the_handoffs_it_declared(tmp_path):
    """Drawn the same way a router's branches are, because they are the same
    thing one level up -- so the view has one arrow to learn, not two."""
    then = [SimpleNamespace(when="run.change", to="review", label="changed")]
    daemon = stub_daemon(tmp_path, [stub_runner(then=then)])
    client = TestClient(create_app(daemon))

    row = client.get("/api/tasks").json()["tasks"][0]
    assert row["then"] == [{"to": "review", "label": "changed"}]


def test_a_branch_with_no_label_is_drawn_with_its_condition(tmp_path):
    """The same fallback RouterNode uses when it records which arm it took, so
    the board and the run record never disagree about what to call an arrow."""
    then = [SimpleNamespace(when="run.steps > 2", to="review", label=None)]
    daemon = stub_daemon(tmp_path, [stub_runner(then=then)])
    client = TestClient(create_app(daemon))

    row = client.get("/api/tasks").json()["tasks"][0]
    assert row["then"] == [{"to": "review", "label": "run.steps > 2"}]


def test_the_wiring_carries_no_prompts(tmp_path):
    """A board paint reaches every browser watching. Prompts are long, are of
    no use to a drawing, and are the kind of thing a graph hides secrets in."""
    daemon = stub_daemon(tmp_path, [stub_runner()])
    client = TestClient(create_app(daemon))

    shape = client.get("/api/tasks").json()["tasks"][0]["shape"]
    assert not any("prompt" in node or "system" in node for node in shape["nodes"])


def test_each_node_reports_the_model_it_would_call(tmp_path):
    """The graph still names a role; the board resolves it, exactly as the
    runtime does, so the picture cannot claim one model and the run make
    another. A router calls nothing, and says so."""
    daemon = stub_daemon(tmp_path, [stub_runner()])
    client = TestClient(create_app(daemon))

    shape = client.get("/api/tasks").json()["tasks"][0]["shape"]
    models = {node["id"]: node["model"] for node in shape["nodes"]}
    assert models == {
        "classify": "llama3.2:3b",   # its role
        "route": None,               # a router calls no model
        "answer": "claude-opus-5",   # no role: through the graph's default_role
    }


def test_one_graph_on_two_bindings_reports_two_models(tmp_path):
    """Which is why the model is drawn inside a task's border and never on the
    graph: the same file is a different afternoon under a different binding."""
    local = {
        "providers": {"ollama": {"type": "ollama", "base_url": "http://localhost:11434"}},
        "default": {"provider": "ollama", "model": "qwen3:8b"},
    }
    daemon = stub_daemon(
        tmp_path,
        [stub_runner(name="triage"), stub_runner(name="nightly", binding=local)],
    )
    client = TestClient(create_app(daemon))

    rows = {row["name"]: row["shape"] for row in client.get("/api/tasks").json()["tasks"]}
    said = lambda shape: [n["model"] for n in shape["nodes"] if n["id"] == "answer"]
    assert said(rows["triage"]) == ["claude-opus-5"]
    assert said(rows["nightly"]) == ["qwen3:8b"]


def test_a_role_the_binding_never_declares_reports_what_will_really_run(tmp_path):
    """`resolve` falls back to `default` for any role at all, so `classifer` is
    not an error -- it is the expensive model, quietly. The daemon warns about
    it at load; this puts it in the picture, where two nodes that were meant to
    differ show the same id side by side."""
    typo = {
        "name": "support-triage",
        "entry": "classify",
        "nodes": [{"id": "classify", "type": "agent", "prompt": "x", "role": "classifer"}],
    }
    daemon = stub_daemon(tmp_path, [stub_runner(graph=typo)])
    client = TestClient(create_app(daemon))

    shape = client.get("/api/tasks").json()["tasks"][0]["shape"]
    assert [node["model"] for node in shape["nodes"]] == ["claude-opus-5"]


def test_a_binding_with_no_default_leaves_the_model_unknown(tmp_path):
    """A board that cannot say what runs a node is worth more than a board that
    will not paint -- the same rule the review state already follows."""
    bare = {"providers": {"claude": {"type": "anthropic"}}}
    daemon = stub_daemon(tmp_path, [stub_runner(binding=bare)])
    client = TestClient(create_app(daemon))

    response = client.get("/api/tasks")
    assert response.status_code == 200
    shape = response.json()["tasks"][0]["shape"]
    assert all(node["model"] is None for node in shape["nodes"])


def test_the_wiring_carries_no_credentials(tmp_path):
    """Only the bare model id crosses. A provider knows a base_url and the name
    of the variable a key comes from, and neither has any business on a board."""
    daemon = stub_daemon(tmp_path, [stub_runner()])
    client = TestClient(create_app(daemon))

    body = client.get("/api/tasks").text
    assert "base_url" not in body
    assert "api_key_env" not in body
    assert "localhost:11434" not in body


def test_flows_asks_every_runner_at_once(tmp_path):
    """Each runner's review state costs two git subprocesses, ~100ms of spawn
    on Windows. Asked one runner at a time, the first paint of a board of N
    tasks waits ~2N spawns; asked together it waits for the slowest one."""
    import threading
    import time

    lock = threading.Lock()
    active = 0
    peak = 0

    class SlowPoint:
        def pending(self):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return []

        def into(self):
            return "main"

    runners = [
        stub_runner(name=f"task{i}", workspace=SlowPoint()) for i in range(4)
    ]
    client = TestClient(create_app(stub_daemon(tmp_path, runners)))

    body = client.get("/api/tasks").json()
    assert [row["name"] for row in body["tasks"]] == [f"task{i}" for i in range(4)]
    assert peak > 1  # overlapping, not one after another


def test_runs_index_and_detail_and_404(tmp_path):
    daemon = stub_daemon(tmp_path)
    daemon.store.append(Event(run_id="r1", type="run_started", data={"task": "t"}))
    daemon.store.record_summary({"run_id": "r1", "task": "t", "status": "completed"})
    client = TestClient(create_app(daemon))

    runs = client.get("/api/runs").json()["runs"]
    assert runs[0]["run_id"] == "r1"
    detail = client.get("/api/runs/r1").json()
    assert detail["run_id"] == "r1"
    assert detail["events"][0]["type"] == "run_started"
    assert client.get("/api/runs/nope").status_code == 404


def test_root_serves_fallback_without_built_ui(tmp_path, monkeypatch):
    # Point away from the checked-in build so this covers a fresh checkout
    # rather than whatever `npm run build` last left in the package.
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "unbuilt")

    client = TestClient(create_app(stub_daemon(tmp_path)))
    response = client.get("/")
    assert response.status_code == 200
    assert "/api/tasks" in response.text


def test_sse_frame_format():
    assert sse_frame({"type": "x"}) == 'data: {"type": "x"}\n\n'


async def test_event_stream_yields_and_filters(tmp_path):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    stream = _event_stream(store, task="triage")

    async def first_frame():
        return await stream.__anext__()

    task = asyncio.create_task(first_frame())
    await asyncio.sleep(0)  # let the generator subscribe
    # an event for another task is filtered out, ours comes through
    store.append(Event(run_id="a", type="run_started", data={"task": "other"}))
    store.append(Event(run_id="b", type="run_started", data={"task": "triage"}))
    frame = await asyncio.wait_for(task, timeout=2)
    assert '"run_id": "b"' in frame
    await stream.aclose()


def test_built_ui_is_served_from_static(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>poieo</title>")
    (static / "assets" / "app.js").write_text("export default 1;")
    monkeypatch.setattr(server, "STATIC_DIR", static)

    client = TestClient(create_app(stub_daemon(tmp_path)))

    assert "<!doctype html>" in client.get("/").text
    # Vite's index.html asks for /assets/<name>; the mount has to resolve there
    # and not one directory up.
    assert client.get("/assets/app.js").status_code == 200

def daemon_with_a_change(tmp_path, body="print(1)" + chr(10), run_id="r1"):
    """A stub daemon whose one task really has a change to show."""
    repo = make_repo(tmp_path)
    point = Workspace(repo, "chores", tmp_path / "worktrees")
    point.prepare()
    (point.worktree / "new.py").write_text(body, encoding="utf-8")
    change = point.commit(run_id, "did a thing")

    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    store.append(Event(run_id=run_id, type="run_started", data={"task": "chores"}))
    store.record_summary(
        {
            "run_id": run_id,
            "task": "chores",
            "status": "completed",
            "change": change.as_dict(),
        }
    )
    runner = stub_runner(name="chores", workspace=point)
    return SimpleNamespace(runners=[runner], store=store), change


def test_diff_reports_the_files_and_the_patch(tmp_path):
    daemon, change = daemon_with_a_change(tmp_path)
    client = TestClient(create_app(daemon))

    body = client.get("/api/runs/r1/diff").json()

    assert body["run_id"] == "r1"
    assert body["base"] == change.base and body["head"] == change.head
    assert body["files"] == [
        {"path": "new.py", "status": "A", "insertions": 1, "deletions": 0}
    ]
    assert "print(1)" in body["patch"]
    assert body["truncated"] is False


def test_diff_of_a_run_that_changed_nothing_is_not_an_error(tmp_path):
    daemon = stub_daemon(tmp_path, [stub_runner(name="chores")])
    daemon.store.append(Event(run_id="quiet", type="run_started", data={"task": "chores"}))
    daemon.store.record_summary(
        {"run_id": "quiet", "task": "chores", "status": "completed"}
    )
    client = TestClient(create_app(daemon))

    response = client.get("/api/runs/quiet/diff")

    # Nothing to review is information, not a failure.
    assert response.status_code == 200
    assert response.json() == {"run_id": "quiet", "change": None}


def test_diff_of_an_unknown_run_is_404(tmp_path):
    daemon = stub_daemon(tmp_path, [stub_runner(name="chores")])
    client = TestClient(create_app(daemon))
    assert client.get("/api/runs/nope/diff").status_code == 404


def test_diff_truncates_a_huge_patch_but_keeps_the_file_list(tmp_path):
    huge = ("x" * 79 + chr(10)) * 6000  # comfortably past the 400k default
    daemon, _ = daemon_with_a_change(tmp_path, body=huge)
    client = TestClient(create_app(daemon))

    body = client.get("/api/runs/r1/diff").json()

    assert body["truncated"] is True
    assert len(body["patch"]) <= 400_000
    assert body["files"][0]["path"] == "new.py"
    assert body["files"][0]["insertions"] == 6000


def daemon_with_two_changes(tmp_path):
    """Two runs' worth of pending work on one task's branch."""
    repo = make_repo(tmp_path)
    point = Workspace(repo, "chores", tmp_path / "worktrees")
    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    changes = {}

    for run_id, name in (("r1", "one.py"), ("r2", "two.py")):
        point.prepare()
        (point.worktree / name).write_text("print(1)" + chr(10), encoding="utf-8")
        change = point.commit(run_id, f"wrote {name}")
        changes[run_id] = change
        store.append(Event(run_id=run_id, type="run_started", data={"task": "chores"}))
        store.record_summary(
            {
                "run_id": run_id,
                "task": "chores",
                "status": "completed",
                "change": change.as_dict(),
            }
        )

    runner = stub_runner(name="chores", workspace=point)
    return SimpleNamespace(runners=[runner], store=store), repo, changes


def test_flows_reports_how_much_is_waiting_and_where_it_would_go(tmp_path):
    daemon, _, _ = daemon_with_two_changes(tmp_path)
    client = TestClient(create_app(daemon))

    row = client.get("/api/tasks").json()["tasks"][0]
    assert row["pending"] == 2
    # the accept button has to say what it would add to
    assert row["into"] == "main"


def test_flows_reports_nothing_pending_without_a_private_copy(tmp_path):
    daemon = stub_daemon(tmp_path, [stub_runner(name="triage")])
    client = TestClient(create_app(daemon))

    assert client.get("/api/tasks").json()["tasks"][0]["pending"] == 0


def test_accept_puts_the_work_in_the_users_branch(tmp_path):
    daemon, repo, changes = daemon_with_two_changes(tmp_path)
    client = TestClient(create_app(daemon))

    response = client.post("/api/tasks/chores/accept", json={})

    assert response.status_code == 200
    assert response.json() == {"accepted": 2}
    assert head(repo, "main") == changes["r2"].head
    assert (repo / "one.py").exists() and (repo / "two.py").exists()


def test_accept_through_a_run_stops_there(tmp_path):
    daemon, repo, changes = daemon_with_two_changes(tmp_path)
    client = TestClient(create_app(daemon))

    body = client.post("/api/tasks/chores/accept", json={"through_run_id": "r1"}).json()

    assert body == {"accepted": 1}
    assert head(repo, "main") == changes["r1"].head
    assert not (repo / "two.py").exists()


def test_accept_refuses_a_dirty_checkout(tmp_path):
    daemon, repo, _ = daemon_with_two_changes(tmp_path)
    before = head(repo, "main")
    (repo / "README.md").write_text("mine, unsaved", encoding="utf-8")
    client = TestClient(create_app(daemon))

    response = client.post("/api/tasks/chores/accept", json={})

    assert response.status_code == 409
    assert response.json() == {"dirty": ["README.md"]}
    assert head(repo, "main") == before


def test_accept_reports_a_conflict_and_leaves_no_mess(tmp_path):
    repo = make_repo(tmp_path)
    point = Workspace(repo, "chores", tmp_path / "worktrees")
    point.prepare()
    (point.worktree / "README.md").write_text("theirs", encoding="utf-8")
    change = point.commit("r1", "rewrote it")

    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    store.record_summary(
        {"run_id": "r1", "task": "chores", "status": "completed", "change": change.as_dict()}
    )
    (repo / "README.md").write_text("mine", encoding="utf-8")
    git(repo, "commit", "-am", "my own edit")
    before = head(repo, "main")

    daemon = SimpleNamespace(
        runners=[stub_runner(name="chores", workspace=point)], store=store
    )
    response = TestClient(create_app(daemon)).post("/api/tasks/chores/accept", json={})

    assert response.status_code == 409
    assert response.json() == {"conflict": ["README.md"]}
    assert head(repo, "main") == before
    # no half-finished merge left for the user to discover
    assert git(repo, "status", "--porcelain", "--untracked-files=no").strip() == ""


def test_discard_puts_the_branch_back_and_keeps_the_work_reachable(tmp_path):
    daemon, repo, changes = daemon_with_two_changes(tmp_path)
    client = TestClient(create_app(daemon))

    response = client.post("/api/tasks/chores/discard", json={})

    assert response.status_code == 200
    assert response.json() == {"discarded": 2}
    assert head(repo, "poieo/chores") == head(repo, "main")
    assert head(repo, "refs/poieo/discarded/r2") == changes["r2"].head


def test_discard_from_a_run_keeps_the_earlier_work(tmp_path):
    daemon, repo, changes = daemon_with_two_changes(tmp_path)
    client = TestClient(create_app(daemon))

    body = client.post("/api/tasks/chores/discard", json={"from_run_id": "r2"}).json()

    assert body == {"discarded": 1}
    assert head(repo, "poieo/chores") == changes["r1"].head


def test_accept_and_discard_404_on_an_unknown_flow(tmp_path):
    daemon, _, _ = daemon_with_two_changes(tmp_path)
    client = TestClient(create_app(daemon))

    assert client.post("/api/tasks/nope/accept", json={}).status_code == 404
    assert client.post("/api/tasks/nope/discard", json={}).status_code == 404


def test_getting_the_mutation_routes_is_not_allowed(tmp_path):
    # A crawler, a prefetch, or a mistyped curl must never take the work.
    daemon, _, _ = daemon_with_two_changes(tmp_path)
    client = TestClient(create_app(daemon))

    assert client.get("/api/tasks/chores/accept").status_code == 405
    assert client.get("/api/tasks/chores/discard").status_code == 405


def test_accept_survives_a_missing_body(tmp_path):
    daemon, _, _ = daemon_with_two_changes(tmp_path)
    client = TestClient(create_app(daemon))

    assert client.post("/api/tasks/chores/accept").status_code == 200


def test_the_page_is_revalidated_but_its_assets_are_not(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>poieo</title>")
    (static / "assets" / "app-abc123.js").write_text("export default 1;")
    monkeypatch.setattr(server, "STATIC_DIR", static)

    client = TestClient(create_app(stub_daemon(tmp_path)))

    # The document names the build; cache it and a browser keeps running an
    # old app forever, with no way for the reader to know.
    page = client.get("/")
    assert "no-cache" in page.headers["cache-control"]

    # Asset names carry a content hash, so they can never go stale.
    asset = client.get("/assets/app-abc123.js")
    assert "max-age=31536000" in asset.headers["cache-control"]
    assert "immutable" in asset.headers["cache-control"]
