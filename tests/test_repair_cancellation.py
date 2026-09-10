"""A cancelled application must stop its active repair too."""

import asyncio

from test_task_application import CHECK_MADE, policy_config

from poieo.daemon import Daemon
from poieo.tools import CommandResult, LocalExecutor


async def test_cancelling_a_running_repair_stops_tools_and_does_not_save_it(tmp_path, monkeypatch):
    responses = """          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: old}}
          - wrote made.txt
          - tool_calls:
              - {name: run_command, arguments: {command: wait-for-test}}
          - '{"decision":"ready","summary":"Finished repair"}'
"""
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]}, responses=responses)
    driver = Daemon(config)._runners()[0]
    entered, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = LocalExecutor.run_command

    async def command(executor, text, **kwargs):
        if text != "wait-for-test":
            return await original(executor, text, **kwargs)
        entered.set()
        try:
            await release.wait()
        finally:
            stopped.set()
        return CommandResult(0, "finished")

    monkeypatch.setattr(LocalExecutor, "run_command", command)
    running = asyncio.create_task(driver.run_once({}))
    await asyncio.wait_for(entered.wait(), 8)
    running.cancel()
    try:
        await asyncio.wait_for(stopped.wait(), 2)
    finally:
        release.set()
        result = await running
    assert result.application["repair"]["ready"] is False
    assert not (repo / "made.txt").exists()
    assert not driver.cancel.is_set()
