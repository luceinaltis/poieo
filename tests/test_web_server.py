"""The observation API over a stub daemon."""

import asyncio
from types import SimpleNamespace

from starlette.testclient import TestClient

from poieo.store import Event, RunStore
from poieo.web.events import BroadcastStore
from poieo.web.server import create_app, sse_frame, _event_stream


def stub_daemon(tmp_path, runners=()):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    return SimpleNamespace(runners=list(runners), store=store)


def stub_runner(name="triage", status="waiting", current=None, last=None):
    return SimpleNamespace(
        name=name,
        status=status,
        current_run_id=current,
        last_result=last,
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


def test_events_endpoint_handshake(tmp_path):
    client = TestClient(create_app(stub_daemon(tmp_path)))
    with client.stream("GET", "/api/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
