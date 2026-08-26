"""A flow can be paused, resumed, and run right now -- the runner's control seam."""

import asyncio

from poieo.daemon import Daemon, load_config
from poieo.store import NullStore

_GRAPH = """\
name: quick
entry: a
nodes:
  - {id: a, type: llm, role: r, prompt: hi}
"""

_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "done"}}}
default: {provider: fake, model: m}
"""

_SLOW_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {latency: 0.5, responses: {"*": "done"}}}
default: {provider: fake, model: m}
"""


def _config(tmp_path, trigger, binding=_MOCK, graph=_GRAPH):
    (tmp_path / "g.yaml").write_text(graph, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(binding, encoding="utf-8")
    path = tmp_path / "poieo.yaml"
    path.write_text(
        "binding: b.yaml\n"
        "flows:\n"
        "  - name: f\n"
        "    graph: g.yaml\n"
        f"    trigger: {trigger}\n",
        encoding="utf-8",
    )
    return load_config(path)


async def _up(daemon):
    """Start serving and hand back the task once the runner exists."""
    task = asyncio.create_task(daemon.serve(install_signals=False))
    while not daemon.runners:
        await asyncio.sleep(0.01)
    return task


async def _until(predicate, what="the condition", timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


async def _down(daemon, task):
    daemon.stop()
    return await asyncio.wait_for(task, timeout=10)


async def test_pause_skips_due_fires_and_resume_rearms_the_schedule(tmp_path):
    config = _config(
        tmp_path, "{type: interval, every: 0.05s, run_at_start: false}"
    )
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    assert runner.pause() == "paused"
    await asyncio.sleep(0.3)  # several fires come due; every one is skipped
    assert len(runner.results) == 0
    assert runner.status == "paused"

    assert runner.resume() == "waiting"
    await _until(lambda: len(runner.results) >= 1, "a run after resume")
    await _down(daemon, task)


async def test_a_paused_loop_flow_neither_runs_nor_burns_its_schedule(tmp_path):
    """The generator must sit suspended through a pause, not spin through it.

    Five iterations with a 50ms cooldown: an implementation that kept
    consuming fires while paused would exhaust the schedule during the pause,
    and resume would have nothing left to run.
    """
    config = _config(
        tmp_path, "{type: loop, cooldown: 0.05s, max_iterations: 5}"
    )
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    await _until(lambda: len(runner.results) >= 1, "the first run")
    runner.pause()
    await _until(lambda: runner.status == "paused", "the pause to land")
    count = len(runner.results)
    await asyncio.sleep(0.3)
    assert len(runner.results) == count  # nothing ran while paused

    runner.resume()
    await _until(lambda: len(runner.results) > count, "a run after resume")
    await _down(daemon, task)


async def test_run_now_is_the_first_way_a_manual_flow_ever_runs(tmp_path):
    config = _config(tmp_path, "{type: manual}")
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    await asyncio.sleep(0.05)
    assert len(runner.results) == 0  # never fires on its own

    assert runner.run_now() is True
    await _until(lambda: len(runner.results) == 1, "the manual run")
    assert runner.results[0].status == "completed"
    await _down(daemon, task)


async def test_run_now_on_a_paused_flow_runs_once_and_stays_paused(tmp_path):
    config = _config(
        tmp_path, "{type: interval, every: 60s, run_at_start: false}"
    )
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    runner.pause()
    assert runner.run_now() is True
    await _until(lambda: len(runner.results) == 1, "the probe run")
    await _until(lambda: runner.status == "paused", "the pause to hold")
    await asyncio.sleep(0.1)
    assert len(runner.results) == 1  # once means once
    await _down(daemon, task)


async def test_run_now_mid_run_is_refused(tmp_path):
    config = _config(tmp_path, "{type: manual}", binding=_SLOW_MOCK)
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await _until(lambda: runner.status == "running", "the run to start")
    assert runner.run_now() is False  # iterations never overlap
    await _until(lambda: len(runner.results) == 1, "the run to finish")
    await asyncio.sleep(0.1)
    assert len(runner.results) == 1  # and no second run sneaked in behind it
    await _down(daemon, task)


_JSON_GRAPH = """\
name: wants-json
entry: a
nodes:
  - {id: a, type: llm, role: r, prompt: hi, output: {format: json}}
"""

_PROSE_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "prose, not json"}}}
default: {provider: fake, model: m}
"""


async def test_a_self_paused_flow_comes_back_with_resume(tmp_path):
    """The failure-causes pause used to demand a daemon restart; no longer."""
    config = _config(
        tmp_path,
        "{type: loop, max_iterations: 20}",
        binding=_PROSE_MOCK,
        graph=_JSON_GRAPH,
    )
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    await _until(lambda: runner.status == "paused", "the self-pause")
    assert len(runner.results) == 3

    runner.resume()
    # Still failing identically: three more runs, then paused again --
    # proof the failure counter started over rather than tripping at one.
    await _until(
        lambda: len(runner.results) == 6 and runner.status == "paused",
        "the second self-pause",
    )
    await _down(daemon, task)


async def test_shutdown_reaches_a_paused_runner_promptly(tmp_path):
    config = _config(
        tmp_path, "{type: interval, every: 0.05s, run_at_start: false}"
    )
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    runner.pause()
    await asyncio.sleep(0.15)  # a fire has come due and is being held unrun
    results = await _down(daemon, task)  # wait_for inside is the promptness check
    assert results == []
