"""Optional direction survives an active run and a daemon restart."""

import asyncio

import httpx
import pytest
from test_task_application import policy_config, run_once

from poieo.card import read_journal
from poieo.daemon import Daemon
from poieo.web.server import create_app


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


async def test_direction_left_during_work_is_new_after_the_run_finishes(tmp_path, monkeypatch):
    _, config = policy_config(tmp_path, {"mode": "review"})
    daemon = Daemon(config)
    driver = daemon._runners()[0]
    entered, release = asyncio.Event(), asyncio.Event()
    original = driver._open_change

    async def waiting():
        entered.set()
        await release.wait()
        return await original()

    monkeypatch.setattr(driver, "_open_change", waiting)
    running = asyncio.create_task(driver.run_once({}))
    await asyncio.wait_for(entered.wait(), 5)
    driver.leave_note("Keep the heading next time")
    release.set()
    await running
    fresh = read_journal(config.cards_by_task["chores"].journal_path()).split("What you did before that:")[0]
    assert "Keep the heading next time" in fresh


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
    assert "Keep the heading" in read_journal(config.cards_by_task["chores"].journal_path())
