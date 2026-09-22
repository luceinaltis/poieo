"""Optional direction survives an active run and a daemon restart."""

import asyncio

import httpx
import pytest
from test_task_application import policy_config, run_once

from poieo.daemon import Daemon
from poieo.journal import read_journal
from poieo.web.server import create_app


async def test_an_unavailable_task_lease_is_recorded_without_running_the_task(tmp_path):
    from test_task_workspace import LLM_GRAPH, WRITES_NOTHING

    _, config = policy_config(tmp_path, {"mode": "review"}, workdir=False, graph=LLM_GRAPH, responses=WRITES_NOTHING)
    config.layout().worktrees().write_text("existing user file")
    driver = Daemon(config)._runners()[0]
    result = await driver.run_once({})
    assert result.status == "asking"
    assert "could not coordinate" in result.application["error"]
    assert driver.store.summary(result.run_id)["status"] == "asking"
    assert result.steps == 0
    assert config.layout().worktrees().read_text() == "existing user file"


@pytest.mark.parametrize("folder", [None, "plain"])
async def test_unprotected_tasks_keep_direction_until_a_run_can_read_it(tmp_path, monkeypatch, folder):
    import yaml
    from test_task_workspace import LLM_GRAPH, WRITES_NOTHING

    from poieo.daemon import load_config

    _, config = policy_config(tmp_path, {"mode": "review"}, workdir=False, graph=LLM_GRAPH, responses=WRITES_NOTHING)
    if folder:
        (tmp_path / folder).mkdir()
        path = tmp_path / "cards" / "chores.yaml"
        card = yaml.safe_load(path.read_text())
        card["folder"] = f"../{folder}"
        path.write_text(yaml.safe_dump(card))
        config = load_config(tmp_path / "d.yaml")
    active, second = Daemon(config)._runners()[0], Daemon(config)._runners()[0]
    entered, release = asyncio.Event(), asyncio.Event()
    original = active._open_change

    async def waiting():
        entered.set()
        await release.wait()
        return await original()

    monkeypatch.setattr(active, "_open_change", waiting)
    running = asyncio.create_task(active.run_once({}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        second.leave_note("Keep the heading next time")
        refused = await second.run_once({})
        assert refused.status == "asking"
        assert "already running" in refused.application["error"]
    finally:
        release.set()
        await running
    fresh = read_journal(config.cards_by_task["chores"].journal_path()).split("What you did before that:")[0]
    assert "Keep the heading next time" in fresh


async def test_a_second_runner_cannot_deliver_direction_into_an_active_runs_bookmark(tmp_path, monkeypatch):
    _, config = policy_config(tmp_path, {"mode": "review"})
    active, board = Daemon(config)._runners()[0], Daemon(config)._runners()[0]
    entered, release = asyncio.Event(), asyncio.Event()
    original = active._open_change

    async def waiting():
        entered.set()
        await release.wait()
        return await original()

    monkeypatch.setattr(active, "_open_change", waiting)
    running = asyncio.create_task(active.run_once({}))
    await asyncio.wait_for(entered.wait(), 5)
    board.leave_note("Keep the heading next time")
    release.set()
    await running
    fresh = read_journal(config.cards_by_task["chores"].journal_path()).split("What you did before that:")[0]
    assert "Keep the heading next time" in fresh


async def test_cli_reads_queued_direction_only_after_owning_the_task(tmp_path):
    import json

    from typer.testing import CliRunner

    from poieo.cli import app

    _, config = policy_config(tmp_path, {"mode": "review"})
    driver = Daemon(config)._runners()[0]
    async with driver._change_lock:
        driver.leave_note("Keep the heading next time")
    # A marker makes CLI and daemon share the same configured run store.
    (tmp_path / "poieo.yaml").write_text((tmp_path / "d.yaml").read_text())
    reply = await asyncio.to_thread(CliRunner().invoke, app, ["run", str(tmp_path / "cards" / "chores.yaml"), "--json"])
    assert reply.exit_code == 0, reply.output
    run_id = json.loads(reply.output)["run_id"]
    events = list(driver.store.events(run_id))
    started = next(event for event in events if event["type"] == "run_started")
    assert "Keep the heading next time" in started["data"]["input"]["journal"]


TWO_TURNS = """          - tool_calls:
              - {name: list_dir, arguments: {}}
          - "Skipped the drafts, as told."
"""


def _said_during_the_first_turn(monkeypatch, driver, text):
    """Leave the words while the model's first turn is being answered, as a
    person watching the run would; the answer to the note is captured."""
    from poieo.providers.mock import MockProvider

    calls = 0
    answers = []
    original = MockProvider.complete

    async def complete(self, request):
        nonlocal calls
        calls += 1
        if calls == 1:
            answers.append(driver.leave_note(text))
        return await original(self, request)

    monkeypatch.setattr(MockProvider, "complete", complete)
    return answers


async def test_direction_left_during_work_is_heard_by_that_run_and_kept(tmp_path, monkeypatch):
    """It used to wait for the next run. Now the run that is going hears it at
    its next model turn, and the journal keeps the words from the moment they
    were said -- so after the run they are history, not news."""
    _, config = policy_config(tmp_path, {"mode": "review"}, responses=TWO_TURNS)
    driver = Daemon(config)._runners()[0]
    answers = _said_during_the_first_turn(monkeypatch, driver, "Keep the heading next time")

    result = await driver.run_once({})

    assert answers == [{"status": "delivered"}]
    journal = read_journal(config.cards_by_task["chores"].journal_path())
    assert "Keep the heading next time" in journal
    assert "Keep the heading next time" not in journal.split("What you did before that:")[0]
    heard = [e for e in driver.store.events(result.run_id) if e["type"] == "node_directed"]
    assert [(e["data"]["turn"], e["data"]["text"]) for e in heard] == [(2, "Keep the heading next time")]


async def test_queued_direction_is_delivered_after_restart_before_reading_input(tmp_path, monkeypatch):
    _, config = policy_config(tmp_path, {"mode": "review"})
    original = Daemon(config)._runners()[0]
    async with original._change_lock:
        original.leave_note("Keep the heading next time")
    restarted = Daemon(config)._runners()[0]
    payloads = []
    reader = restarted.task.read_input

    def read(_self, config):
        payload = reader(config)
        payloads.append(str(payload))
        return payload

    monkeypatch.setattr(type(restarted.task), "read_input", read)
    from datetime import datetime

    from poieo.daemon.triggers import Firing

    await restarted._one_run(Firing(iteration=1, at=datetime.now(), reason="run now"))
    assert "Keep the heading next time" in payloads[0]


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001, None])
async def test_empty_or_oversized_direction_is_refused(tmp_path, text):
    _, config = policy_config(tmp_path, {"mode": "review"})
    daemon, _ = await run_once(config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(daemon)), base_url="http://localhost"
    ) as client:
        reply = await client.post(f"/api/tasks/{config.display_name}/chores/note", json={"text": text})
    assert reply.status_code == 400


async def test_the_board_saves_optional_direction_without_starting_a_run(tmp_path):
    _, config = policy_config(tmp_path, {"mode": "review"})
    daemon, result = await run_once(config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(daemon)), base_url="http://localhost"
    ) as client:
        reply = await client.post(f"/api/tasks/{config.display_name}/chores/note", json={"text": "Keep the heading"})
    assert reply.status_code == 200
    assert len(daemon.runners[0].results) == 1
    assert daemon.runners[0].results[0].run_id == result.run_id
    queued = list(config.layout().notes("chores").glob("*.json"))
    assert len(queued) == 1 and "Keep the heading" in queued[0].read_text()


async def test_direction_left_while_a_run_is_going_reaches_it_at_once(tmp_path, monkeypatch):
    """A run in flight hears the words at its next model turn as the person's
    own message; the journal keeps them now, and nothing waits in the notes
    folder for a next run."""
    from poieo.providers.mock import MockProvider

    _, config = policy_config(tmp_path, {"mode": "review"}, responses=TWO_TURNS)
    driver = Daemon(config)._runners()[0]
    answers = _said_during_the_first_turn(monkeypatch, driver, "Skip the drafts folder.")
    seen = []
    listening = MockProvider.complete

    async def complete(self, request):
        seen.append([m for m in request.messages if m.get("role") == "user"])
        return await listening(self, request)

    monkeypatch.setattr(MockProvider, "complete", complete)

    result = await driver.run_once({})

    assert answers == [{"status": "delivered"}]
    assert result.status == "completed"
    assert {"role": "user", "content": "Skip the drafts folder."} in seen[1]
    assert all(m.get("content") != "Skip the drafts folder." for m in seen[0])
    card = config.cards_by_task["chores"]
    assert "Skip the drafts folder." in read_journal(card.journal_path())
    assert list(config.layout().notes(card.slug).glob("*.json")) == []


async def test_direction_left_before_the_prompt_is_read_takes_the_durable_road(tmp_path, monkeypatch):
    """Between the run starting and its prompt being read from the journal, a
    note is kept for the next run as before: queued then, it would be both in
    the prompt and heard again at the first turn."""
    _, config = policy_config(tmp_path, {"mode": "review"})
    driver = Daemon(config)._runners()[0]
    entered, release = asyncio.Event(), asyncio.Event()
    original = driver._open_change

    async def waiting():
        entered.set()
        await release.wait()
        return await original()

    monkeypatch.setattr(driver, "_open_change", waiting)
    running = asyncio.create_task(driver.run_once({}))
    await asyncio.wait_for(entered.wait(), 5)
    answer = driver.leave_note("Keep the heading next time")
    release.set()
    result = await running

    assert answer == {"status": "saved"}
    assert [e for e in driver.store.events(result.run_id) if e["type"] == "node_directed"] == []
    # The durable road: delivered into the journal as news once the run is
    # done, for the next run to read, as it always was.
    fresh = read_journal(config.cards_by_task["chores"].journal_path()).split("What you did before that:")[0]
    assert "Keep the heading next time" in fresh
