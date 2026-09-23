"""Asking before a tool acts: a step can be told to wait for a person.

`ask_before` names the kinds of call that wait -- `edits` (writing, editing or
appending to a file) and `commands` (running one). When the model reaches for
one, the run says what it wants to do and waits; a person allows it or not,
and a call not allowed never runs: the model is told so, and goes on. Reading
never waits. With nobody to ask -- a run from the terminal -- the answer is no.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import down, until, up
from test_card import write_card
from test_runtime import _CapturingStore, agent_graph, mock_binding

from poieo.card import expand, load_card
from poieo.daemon import Daemon, load_config
from poieo.errors import SpecError
from poieo.graph import GraphSpec
from poieo.providers import ProviderPool
from poieo.runtime.approvals import Approvals
from poieo.runtime.executor import execute
from poieo.store import NullStore
from poieo.web.server import create_app

pytestmark = pytest.mark.usefixtures("daemon_lifecycle")

WRITE = {"tool_calls": [{"name": "write_file", "arguments": {"path": "out.txt", "content": "hi"}}]}


async def _run(tmp_path, answer: bool | None, script, ask_before=("edits",)):
    """Run one step, answering its first question with `answer` (None: nobody is there)."""
    graph = agent_graph(tmp_path, tools=["files", "shell"], ask_before=list(ask_before))
    binding = mock_binding({"worker": script})
    store = _CapturingStore()
    approvals = None if answer is None else Approvals()
    async with ProviderPool(binding) as pool:
        running = asyncio.create_task(execute(graph, binding, pool, store, approvals=approvals))
        if approvals is not None:
            await until(lambda: approvals.waiting(), "the step to ask")
            assert approvals.answer(approvals.waiting()[0], answer)
        result = await running
        provider = pool.get("fake")
    return result, store, provider


async def test_an_edit_waits_for_a_person_and_goes_ahead_when_allowed(tmp_path):
    result, store, _ = await _run(tmp_path, True, [WRITE, "done"])

    assert result.status == "completed"
    assert (tmp_path / "out.txt").read_text() == "hi"
    kinds = [event.type for event in store.events]
    assert kinds.index("node_tool_asking") < kinds.index("node_tool_answered") < kinds.index("node_tool_call")
    [asked] = [event for event in store.events if event.type == "node_tool_asking"]
    assert asked.data["name"] == "write_file" and asked.data["kind"] == "edits"
    [answered] = [event for event in store.events if event.type == "node_tool_answered"]
    assert answered.data == {"call_id": asked.data["call_id"], "allowed": True, "turn": 1}


async def test_a_call_not_allowed_never_runs_and_the_model_is_told(tmp_path):
    result, store, provider = await _run(tmp_path, False, [WRITE, "understood"])

    assert result.status == "completed"
    assert not (tmp_path / "out.txt").exists()
    [told] = [m for m in provider.calls[1].messages if m["role"] == "tool"]
    assert "did not allow" in told["content"]
    [call] = [event for event in store.events if event.type == "node_tool_call"]
    assert call.data["error"] is True


async def test_reading_never_waits(tmp_path):
    (tmp_path / "notes.txt").write_text("x")
    read = {"tool_calls": [{"name": "read_file", "arguments": {"path": "notes.txt"}}]}
    graph = agent_graph(tmp_path, tools=["files"], ask_before=["edits", "commands"])
    binding = mock_binding({"worker": [read, "done"]})
    store = _CapturingStore()
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, store, approvals=Approvals())

    assert result.status == "completed"
    assert not [event for event in store.events if event.type == "node_tool_asking"]


async def test_a_command_waits_only_when_commands_are_asked_about(tmp_path):
    run = {"tool_calls": [{"name": "run_command", "arguments": {"command": "echo hi"}}]}
    result, store, _ = await _run(tmp_path, True, [run, "done"], ask_before=("commands",))
    assert [event.data["kind"] for event in store.events if event.type == "node_tool_asking"] == ["commands"]

    graph = agent_graph(tmp_path, tools=["files"], ask_before=["commands"])
    binding = mock_binding({"worker": [WRITE, "done"]})
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, NullStore(), approvals=Approvals())
    assert result.status == "completed"
    assert (tmp_path / "out.txt").exists()


async def test_with_nobody_to_ask_the_answer_is_no(tmp_path):
    result, store, provider = await _run(tmp_path, None, [WRITE, "understood"])

    assert result.status == "completed"
    assert not (tmp_path / "out.txt").exists()
    [told] = [m for m in provider.calls[1].messages if m["role"] == "tool"]
    assert "nobody" in told["content"]


def test_only_a_step_with_hands_asks_first():
    with pytest.raises(ValueError, match="ask_before"):
        GraphSpec.model_validate(
            {
                "name": "g",
                "entry": "a",
                "nodes": [{"id": "a", "type": "command", "command": "echo hi", "ask_before": ["edits"]}],
            }
        )
    with pytest.raises(ValueError):
        agent_graph("/tmp", ask_before=["everything"])


def test_a_chat_card_says_what_it_asks_before(tmp_path):
    card = load_card(
        write_card(
            tmp_path,
            "chat",
            "name: chat\nchat: true\nprompt: Help.\ntools: [files, shell]\nask_before: [edits, commands]\n",
        )
    )
    _, graph = expand(card)
    assert graph.nodes[0].ask_before == ["edits", "commands"]

    with pytest.raises(SpecError, match="ask_before"):
        load_card(write_card(tmp_path, "nightly", "name: nightly\nprompt: Tidy.\nask_before: [edits]\n"))


_MOCK = """\
name: mock
providers:
  fake:
    type: mock
    options:
      responses:
        "*":
          - tool_calls: [{name: write_file, arguments: {path: out.txt, content: hi}}]
          - done
default: {provider: fake, model: m}
"""


async def test_a_person_answers_from_the_board(tmp_path):
    work = tmp_path / "project"
    write_card(tmp_path, "chat", "name: chat\nchat: true\nprompt: Help.\ntools: [files]\nask_before: [edits]\n")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "poieo.yaml").write_text("binding: b.yaml\ntasks: tasks\n", encoding="utf-8")
    daemon = Daemon(load_config(tmp_path / "poieo.yaml"), store=NullStore())
    serve = await up(daemon)
    runner = daemon.runners[0]
    try:
        transport = httpx.ASGITransport(app=create_app(daemon))
        async with httpx.AsyncClient(transport=transport, base_url="http://poieo") as client:
            project = daemon.config.display_name
            await client.post(f"/api/tasks/{project}/chat/run", json={"message": "write it", "thread": "t-1"})
            await until(lambda: runner.approvals is not None and runner.approvals.waiting(), "the question")
            call = runner.approvals.waiting()[0]

            nothing = await client.post(f"/api/tasks/{project}/chat/approve", json={"call": "nope", "allow": True})
            assert nothing.status_code == 409
            bad = await client.post(f"/api/tasks/{project}/chat/approve", json={"call": call})
            assert bad.status_code == 400

            answered = await client.post(f"/api/tasks/{project}/chat/approve", json={"call": call, "allow": True})
            assert answered.status_code == 200
            await until(lambda: len(runner.results) == 1, "the run to finish")
            assert (work / "out.txt").read_text() == "hi"
    finally:
        await down(daemon, serve)


async def test_a_calls_time_is_the_tools_not_the_persons(tmp_path, monkeypatch):
    """Time spent waiting for a person is not time the tool took."""
    from poieo.runtime import nodes

    now = {"t": 1000.0}
    monkeypatch.setattr(nodes.time, "monotonic", lambda: now["t"])
    graph = agent_graph(tmp_path, tools=["files"], ask_before=["edits"])
    binding = mock_binding({"worker": [WRITE, "done"]})
    store = _CapturingStore()
    approvals = Approvals()

    async def answered_after_half_an_hour(call_id, cancel=None):
        now["t"] += 1800
        return True

    approvals.ask = answered_after_half_an_hour
    async with ProviderPool(binding) as pool:
        await execute(graph, binding, pool, store, approvals=approvals)

    [call] = [event for event in store.events if event.type == "node_tool_call"]
    assert call.data["duration_ms"] < 60_000
