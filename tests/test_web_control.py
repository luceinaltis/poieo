"""The control routes: the board's three verbs reach the runner."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
from conftest import card
from starlette.testclient import TestClient

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
        self.task = SimpleNamespace(graph=SimpleNamespace(name="support-triage"))
        self.calls = []
        self._asking = None

    def waiting_on(self, question="Land it?", choices=("land", "hold")):
        self._asking = SimpleNamespace(
            run_id="r9",
            asked={"node": "confirm", "question": question, "choices": list(choices)},
        )
        return self

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

    def asking(self):
        return self._asking

    def answer(self, choice):
        self.calls.append(f"answer:{choice}")
        if self._asking is None:
            return False
        if choice not in self._asking.asked["choices"]:
            return False
        self._asking = None
        return True


# The project every stub runner here belongs to. Its name is in the address of
# each control route, so the tests spell it once.
BOARD = SimpleNamespace(display_name="board", base_dir=Path("/nowhere"))


def _client(*runners):
    runners = list(runners)
    for runner in runners:
        runner.config = BOARD
    daemon = SimpleNamespace(
        runners=runners,
        store=None,
        config=BOARD,
        projects=[SimpleNamespace(config=BOARD, store=None)],
    )
    return TestClient(create_app(daemon))


def test_pause_and_resume_answer_the_resulting_status():
    runner = StubRunner()
    client = _client(runner)

    assert client.post(f"/api/tasks/{BOARD.display_name}/triage/pause").json() == {"status": "paused"}
    assert client.post(f"/api/tasks/{BOARD.display_name}/triage/resume").json() == {"status": "waiting"}
    assert runner.calls == ["pause", "resume"]


def test_pause_twice_and_resume_at_rest_are_idempotent():
    runner = StubRunner()
    client = _client(runner)

    assert client.post(f"/api/tasks/{BOARD.display_name}/triage/pause").status_code == 200
    assert client.post(f"/api/tasks/{BOARD.display_name}/triage/pause").status_code == 200
    assert client.post(f"/api/tasks/{BOARD.display_name}/triage/pause").json() == {"status": "paused"}

    assert client.post(f"/api/tasks/{BOARD.display_name}/triage/resume").status_code == 200
    assert client.post(f"/api/tasks/{BOARD.display_name}/triage/resume").status_code == 200
    assert client.post(f"/api/tasks/{BOARD.display_name}/triage/resume").json() == {"status": "waiting"}


def test_run_fires_when_the_flow_is_at_rest():
    runner = StubRunner()
    client = _client(runner)

    response = client.post(f"/api/tasks/{BOARD.display_name}/triage/run")
    assert response.status_code == 200
    assert response.json() == {"status": "starting"}
    assert runner.calls == ["run_now"]


def test_run_mid_run_is_409_and_names_the_run():
    runner = StubRunner(status="running")
    client = _client(runner)

    response = client.post(f"/api/tasks/{BOARD.display_name}/triage/run")
    assert response.status_code == 409
    assert response.json() == {"error": "a run is in flight", "run_id": "r7"}


def test_all_three_verbs_404_on_an_unknown_flow():
    client = _client(StubRunner())
    for verb in ("pause", "resume", "run"):
        assert client.post(f"/api/tasks/nope/{verb}").status_code == 404


def test_getting_a_control_route_is_not_allowed():
    # Same rule as accept/discard: a crawler or a prefetch must change nothing.
    runner = StubRunner()
    client = _client(runner)
    for verb in ("pause", "resume", "run"):
        assert client.get(f"/api/tasks/{BOARD.display_name}/triage/{verb}").status_code == 405
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
            body = (await client.get("/api/tasks")).json()
            return body["tasks"][0]["status"]

        response = await client.post(f"/api/tasks/{daemon.config.display_name}/f/run")
        assert response.json() == {"status": "starting"}
        await _until(lambda: len(runner.results) == 1, "the manual run")
        assert runner.results[0].status == "completed"

        assert (await client.post(f"/api/tasks/{daemon.config.display_name}/f/pause")).json() == {"status": "paused"}
        assert await board_status() == "paused"

        assert (await client.post(f"/api/tasks/{daemon.config.display_name}/f/resume")).json() == {"status": "waiting"}
        assert await board_status() == "waiting"

    daemon.stop()
    await asyncio.wait_for(serve, timeout=10)


# -- answering a question a run left ------------------------------------------


def test_answering_reaches_the_runner():
    runner = StubRunner().waiting_on()
    client = _client(runner)

    reply = client.post(
        f"/api/tasks/{BOARD.display_name}/triage/answer", json={"choice": "land"}
    )

    assert reply.status_code == 200
    assert reply.json() == {"status": "answered", "answer": "land"}
    assert runner.calls == ["answer:land"]


def test_a_task_that_asked_nothing_says_so():
    """409, not 404: the task is there, it just has no question open. A board
    with a stale button must be able to tell those apart."""
    client = _client(StubRunner())

    reply = client.post(
        f"/api/tasks/{BOARD.display_name}/triage/answer", json={"choice": "land"}
    )

    assert reply.status_code == 409
    assert "waiting" in reply.json()["error"]


def test_an_answer_that_was_not_offered_is_refused_with_the_ones_that_were():
    client = _client(StubRunner().waiting_on())

    reply = client.post(
        f"/api/tasks/{BOARD.display_name}/triage/answer", json={"choice": "merge"}
    )

    assert reply.status_code == 400
    assert reply.json()["choices"] == ["land", "hold"]


def test_answering_a_task_that_is_not_there_is_a_404():
    client = _client(StubRunner())

    reply = client.post(
        f"/api/tasks/{BOARD.display_name}/nope/answer", json={"choice": "land"}
    )

    assert reply.status_code == 404
