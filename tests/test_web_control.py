"""The control routes: the board's three verbs reach the runner."""

import asyncio
from types import SimpleNamespace

import httpx
from starlette.testclient import TestClient

from conftest import card
from poieo.daemon import Daemon, load_config
from poieo.store import NullStore
from poieo.web.server import create_app


# -- the routes, over a stub runner -------------------------------------------


class StubRunner:
    """Answers the control verbs the way TaskRunner's contract promises."""

    def __init__(self, name="triage", status="waiting"):
        self.name = name
        self.status = status
        self.current_run_id = "r7" if status == "running" else None
        self.last_result = None
        self.workspace = None
        self.trigger = SimpleNamespace(describe="interval 30s")
        self.flow = SimpleNamespace(graph=SimpleNamespace(name="support-triage"))
        self.calls = []

    def pause(self):
        self.calls.append("pause")
        if self.status == "waiting":
            self.status = "paused"
        return self.status

    def resume(self):
        self.calls.append("resume")
        if self.status == "paused":
            self.status = "waiting"
        return self.status

    def run_now(self):
        self.calls.append("run_now")
        return self.status != "running"


def _client(*runners):
    daemon = SimpleNamespace(runners=list(runners), store=None)
    return TestClient(create_app(daemon))


def test_pause_and_resume_answer_the_resulting_status():
    runner = StubRunner()
    client = _client(runner)

    assert client.post("/api/flows/triage/pause").json() == {"status": "paused"}
    assert client.post("/api/flows/triage/resume").json() == {"status": "waiting"}
    assert runner.calls == ["pause", "resume"]


def test_pause_twice_and_resume_at_rest_are_idempotent():
    runner = StubRunner()
    client = _client(runner)

    assert client.post("/api/flows/triage/pause").status_code == 200
    assert client.post("/api/flows/triage/pause").status_code == 200
    assert client.post("/api/flows/triage/pause").json() == {"status": "paused"}

    assert client.post("/api/flows/triage/resume").status_code == 200
    assert client.post("/api/flows/triage/resume").status_code == 200
    assert client.post("/api/flows/triage/resume").json() == {"status": "waiting"}


def test_run_fires_when_the_flow_is_at_rest():
    runner = StubRunner()
    client = _client(runner)

    response = client.post("/api/flows/triage/run")
    assert response.status_code == 200
    assert response.json() == {"status": "starting"}
    assert runner.calls == ["run_now"]


def test_run_mid_run_is_409_and_names_the_run():
    runner = StubRunner(status="running")
    client = _client(runner)

    response = client.post("/api/flows/triage/run")
    assert response.status_code == 409
    assert response.json() == {"error": "a run is in flight", "run_id": "r7"}


def test_all_three_verbs_404_on_an_unknown_flow():
    client = _client(StubRunner())
    for verb in ("pause", "resume", "run"):
        assert client.post(f"/api/flows/nope/{verb}").status_code == 404


def test_getting_a_control_route_is_not_allowed():
    # Same rule as accept/discard: a crawler or a prefetch must change nothing.
    runner = StubRunner()
    client = _client(runner)
    for verb in ("pause", "resume", "run"):
        assert client.get(f"/api/flows/triage/{verb}").status_code == 405
    assert runner.calls == []


# -- the whole daemon, verbs and board on one event loop ----------------------

_GRAPH = """\
name: quick
entry: a
nodes:
  - {id: a, type: agent, role: r, prompt: hi}
"""

_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "done"}}}
default: {provider: fake, model: m}
"""


def _config(tmp_path, trigger):
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    card(tmp_path / "cards", "f", f"graph: ../g.yaml\ntrigger: {trigger}\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    return load_config(path)


async def _until(predicate, what="the condition", timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


async def test_the_verbs_change_what_the_flows_endpoint_reports(tmp_path):
    """End to end on one event loop, exactly as uvicorn shares the daemon's.

    TestClient would call the runner from another thread's loop; ASGITransport
    keeps the handlers where the runner's primitives live.
    """
    daemon = Daemon(_config(tmp_path, "{type: manual}"), store=NullStore())
    serve = asyncio.create_task(daemon.serve(install_signals=False))
    await _until(lambda: bool(daemon.runners), "the runner")
    runner = daemon.runners[0]

    transport = httpx.ASGITransport(app=create_app(daemon))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://poieo"
    ) as client:
        async def board_status():
            body = (await client.get("/api/flows")).json()
            return body["flows"][0]["status"]

        response = await client.post("/api/flows/f/run")
        assert response.json() == {"status": "starting"}
        await _until(lambda: len(runner.results) == 1, "the manual run")
        assert runner.results[0].status == "completed"

        assert (await client.post("/api/flows/f/pause")).json() == {"status": "paused"}
        assert await board_status() == "paused"

        assert (await client.post("/api/flows/f/resume")).json() == {"status": "waiting"}
        assert await board_status() == "waiting"

    daemon.stop()
    await asyncio.wait_for(serve, timeout=10)
