"""The observation API over a stub daemon."""

import asyncio
from types import SimpleNamespace

from starlette.testclient import TestClient

from test_checkpoint import make_repo

from poieo.checkpoint import Checkpoint
from poieo.store import Event, RunStore
from poieo.web.events import BroadcastStore
from poieo.web.server import create_app, sse_frame, _event_stream


def stub_daemon(tmp_path, runners=()):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    return SimpleNamespace(runners=list(runners), store=store)


def stub_runner(name="triage", status="waiting", current=None, last=None, checkpoint=None):
    return SimpleNamespace(
        name=name,
        status=status,
        current_run_id=current,
        last_result=last,
        checkpoint=checkpoint,
        trigger=SimpleNamespace(describe=f"interval 30s"),
        flow=SimpleNamespace(graph=SimpleNamespace(name="support-triage")),
    )


def test_flows_lists_runner_state(tmp_path):
    last = SimpleNamespace(summary=lambda: {"run_id": "r0", "status": "completed"})
    daemon = stub_daemon(tmp_path, [stub_runner(last=last)])
    client = TestClient(create_app(daemon))

    body = client.get("/api/flows").json()
    assert body["flows"] == [
        {
            "name": "triage",
            "graph": "support-triage",
            "trigger": "interval 30s",
            "status": "waiting",
            "current_run_id": None,
            "last_run": {"run_id": "r0", "status": "completed"},
        }
    ]


def test_runs_index_and_detail_and_404(tmp_path):
    daemon = stub_daemon(tmp_path)
    daemon.store.append(Event(run_id="r1", type="run_started", data={"flow": "t"}))
    daemon.store.record_summary({"run_id": "r1", "flow": "t", "status": "completed"})
    client = TestClient(create_app(daemon))

    runs = client.get("/api/runs").json()["runs"]
    assert runs[0]["run_id"] == "r1"
    detail = client.get("/api/runs/r1").json()
    assert detail["run_id"] == "r1"
    assert detail["events"][0]["type"] == "run_started"
    assert client.get("/api/runs/nope").status_code == 404


def test_root_serves_fallback_without_built_ui(tmp_path):
    client = TestClient(create_app(stub_daemon(tmp_path)))
    response = client.get("/")
    assert response.status_code == 200
    assert "/api/flows" in response.text


def test_sse_frame_format():
    assert sse_frame({"type": "x"}) == 'data: {"type": "x"}\n\n'


async def test_event_stream_yields_and_filters(tmp_path):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    stream = _event_stream(store, flow="triage")

    async def first_frame():
        return await stream.__anext__()

    task = asyncio.create_task(first_frame())
    await asyncio.sleep(0)  # let the generator subscribe
    # an event for another flow is filtered out, ours comes through
    store.append(Event(run_id="a", type="run_started", data={"flow": "other"}))
    store.append(Event(run_id="b", type="run_started", data={"flow": "triage"}))
    frame = await asyncio.wait_for(task, timeout=2)
    assert '"run_id": "b"' in frame
    await stream.aclose()


def daemon_with_a_change(tmp_path, body="print(1)" + chr(10), run_id="r1"):
    """A stub daemon whose one flow really has a change to show."""
    repo = make_repo(tmp_path)
    point = Checkpoint(repo, "chores", tmp_path / "checkpoint")
    point.prepare()
    (point.worktree / "new.py").write_text(body, encoding="utf-8")
    change = point.commit(run_id, "did a thing")

    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    store.append(Event(run_id=run_id, type="run_started", data={"flow": "chores"}))
    store.record_summary(
        {
            "run_id": run_id,
            "flow": "chores",
            "status": "completed",
            "change": change.as_dict(),
        }
    )
    runner = stub_runner(name="chores", checkpoint=point)
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
    daemon.store.append(Event(run_id="quiet", type="run_started", data={"flow": "chores"}))
    daemon.store.record_summary(
        {"run_id": "quiet", "flow": "chores", "status": "completed"}
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
