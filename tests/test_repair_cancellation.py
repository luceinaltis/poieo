"""A cancelled application must stop its active repair too."""

import asyncio

from test_task_application import CHECK_MADE, policy_config

from poieo.daemon import Daemon
from poieo.tools import CommandResult, shell


async def test_repair_deadline_stops_a_late_answer_and_preserves_its_usage(tmp_path, monkeypatch):
    from test_task_workspace import GRAPH

    from poieo.providers.mock import MockProvider

    responses = """          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: old}}
          - wrote made.txt
          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: hi}}
          - '{"decision":"ready","summary":"Finished repair"}'
"""
    graph = GRAPH.format(max_turns=10).replace("prompt: do it", "prompt: do it\n    deadline: 1")
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]}, responses=responses, graph=graph)
    cancelled = asyncio.Event()
    complete = MockProvider.complete

    async def late_answer(self, request):
        if len(self.calls) == 3:
            try:
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                cancelled.set()
                raise
        return await complete(self, request)

    monkeypatch.setattr(MockProvider, "complete", late_answer)
    driver = Daemon(config)._runners()[0]
    result = await driver.run_once({})

    assert result.application["status"] == "blocked"
    assert cancelled.is_set()
    assert not driver.cancel.is_set()
    assert not (repo / "made.txt").exists()
    assert driver.workspace.pending()
    repair = result.application["repair"]
    assert repair["ready"] is False
    assert "time limit" in repair["reason"]
    recorded = driver.store.summary(repair["run_id"])
    assert recorded["status"] == "aborted"
    assert recorded["usage"]["input_tokens"] > 0


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
    original = shell.run_here

    async def command(executor, text, **kwargs):
        if text != "wait-for-test":
            return await original(executor, text, **kwargs)
        entered.set()
        try:
            await release.wait()
        finally:
            stopped.set()
        return CommandResult(0, "finished")

    monkeypatch.setattr(shell, "run_here", command)
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
