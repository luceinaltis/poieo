"""A conversation is a task, and each message is one of its runs.

A card that says `chat: true` is the task the board's chat speaks to. It
never fires by itself; each message starts one run, which reads what was said
before in the same thread from the task's own run records, not from the
journal, and answers. It keeps no journal, because its history is its runs.
"""

from __future__ import annotations

import httpx
import pytest
from conftest import down, until, up
from test_card import write_card

from poieo.card import chat_transcript, expand, load_card, record_run
from poieo.daemon import Daemon, load_config
from poieo.errors import SpecError
from poieo.runtime.context import RunResult
from poieo.store import RunStore
from poieo.web.server import create_app

pytestmark = pytest.mark.usefixtures("daemon_lifecycle")


def test_a_chat_card_waits_to_be_spoken_to_and_answers_what_was_said(tmp_path):
    path = write_card(tmp_path, "chat", "name: chat\nchat: true\nprompt: Help with this project.\n")
    task, graph = expand(load_card(path))

    assert task.trigger.type == "manual"
    [node] = graph.nodes
    assert node.prompt == "{{ input.message }}"
    assert "Help with this project." in node.system
    assert "{{ input.transcript }}" in node.system
    assert "{{ input.journal }}" not in node.system


@pytest.mark.parametrize("schedule", ["every: 1h\n", "at: '0 9 * * *'\n", "trigger: {type: loop}\n"])
def test_a_chat_card_takes_no_schedule(tmp_path, schedule):
    path = write_card(tmp_path, "chat", f"name: chat\nchat: true\nprompt: Help.\n{schedule}")

    with pytest.raises(SpecError, match="waits to be spoken to"):
        load_card(path)


def _row(message, said, thread="t-1"):
    return {"message": message, "said": said, "thread": thread, "status": "completed"}


def test_the_transcript_is_the_threads_runs_oldest_first():
    newest_first = [
        _row("and the tests?", "they pass"),
        _row("elsewhere", "other thread", thread="t-2"),
        {"said": "a run nobody spoke to", "status": "completed"},
        _row("what is in src?", "the package"),
    ]

    assert chat_transcript(newest_first, "t-1") == (
        "person: what is in src?\nyou: the package\n\nperson: and the tests?\nyou: they pass"
    )


def test_a_new_thread_says_it_is_the_start():
    assert chat_transcript([_row("hi", "hello")], "t-9") == "(this is the start of the conversation)"


def test_a_long_thread_keeps_its_newest_turns():
    rows = [_row(f"message {i}", f"answer {i}") for i in reversed(range(100))]

    kept = chat_transcript(rows, "t-1")

    assert "message 99" in kept and "message 0\n" not in kept
    assert kept.startswith("(earlier turns left out)")


def test_a_chat_card_keeps_no_journal(tmp_path):
    card = load_card(write_card(tmp_path, "chat", "name: chat\nchat: true\nprompt: Help.\n"))

    done = RunResult(
        run_id="r1",
        task="chat",
        graph="chat",
        status="completed",
        started_at="2026-09-23T00:00:00Z",
        finished_at="2026-09-23T00:00:01Z",
        steps=1,
        path=["work"],
        usage={},
        outputs={"work": "hi"},
        state={},
    )

    record_run(card, done)

    assert not card.journal_path().exists()


_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "an answer"}}}
default: {provider: fake, model: m}
"""


async def test_the_second_message_hears_the_first(tmp_path):
    write_card(tmp_path, "chat", "name: chat\nchat: true\nprompt: Help.\ntools: []\n")
    write_card(tmp_path, "chores", "name: chores\nprompt: Tidy.\ntools: []\ntrigger: {type: manual}\n")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "poieo.yaml").write_text("binding: b.yaml\ntasks: tasks\n", encoding="utf-8")
    daemon = Daemon(load_config(tmp_path / "poieo.yaml"), store=RunStore(tmp_path / "runs"))
    serve = await up(daemon)
    [runner] = [one for one in daemon.runners if one.name == "chat"]

    try:
        transport = httpx.ASGITransport(app=create_app(daemon))
        async with httpx.AsyncClient(transport=transport, base_url="http://poieo") as client:
            project = daemon.config.display_name
            rows = {row["name"]: row for row in (await client.get("/api/tasks")).json()["tasks"]}
            assert rows["chat"]["chat"] is True
            assert rows["chores"]["chat"] is False

            await client.post(f"/api/tasks/{project}/chat/run", json={"message": "what is here?", "thread": "t-1"})
            await until(lambda: len(runner.results) == 1, "the first message")
            assert runner._run_input["transcript"] == "(this is the start of the conversation)"

            await client.post(f"/api/tasks/{project}/chat/run", json={"message": "and then?", "thread": "t-1"})
            await until(lambda: len(runner.results) == 2, "the second message")
            assert runner._run_input["transcript"] == "person: what is here?\nyou: an answer"
            assert runner._run_input["message"] == "and then?"
    finally:
        await down(daemon, serve)
