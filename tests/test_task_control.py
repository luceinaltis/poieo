"""A task can be paused, resumed, and run right now -- the runner's control seam."""

import asyncio

import pytest
from conftest import card, down, timer_barrier, until, up

from poieo.daemon import Daemon, load_config
from poieo.store import NullStore

pytestmark = pytest.mark.usefixtures("daemon_lifecycle")

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

_SLOW_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {latency: 0.5, responses: {"*": "done"}}}
default: {provider: fake, model: m}
"""


def _config(tmp_path, trigger, binding=_MOCK, graph=_GRAPH):
    (tmp_path / "g.yaml").write_text(graph, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(binding, encoding="utf-8")
    card(tmp_path / "cards", "f", f"graph: ../g.yaml\ntrigger: {trigger}\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    return load_config(path)


async def _wait_until_pause_is_active(runner):
    await until(
        lambda: runner.status == "paused" and not runner._wake.is_set(),
        "the runner to enter its paused wait",
    )


async def test_pause_skips_due_fires_and_resume_rearms_the_schedule(tmp_path):
    config = _config(tmp_path, "{type: interval, every: 0.05s, run_at_start: false}")
    daemon = Daemon(config, store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    assert runner.pause() == "paused"
    await asyncio.sleep(0.3)  # several fires come due; every one is skipped
    assert len(runner.results) == 0
    assert runner.status == "paused"

    assert runner.resume() == "waiting"
    await until(lambda: len(runner.results) >= 1, "a run after resume")
    await down(daemon, task)


async def test_a_paused_loop_task_neither_runs_nor_burns_its_schedule(tmp_path, monkeypatch):
    """The generator must sit suspended through a pause, not spin through it.

    Five iterations with a 50ms cooldown: an implementation that kept
    consuming fires while paused would exhaust the schedule during the pause,
    and resume would have nothing left to run.
    """
    wait_for_timer = timer_barrier(monkeypatch)
    config = _config(tmp_path, "{type: loop, cooldown: 0.05s, max_iterations: 5}")
    daemon = Daemon(config, store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    await until(lambda: len(runner.results) >= 1, "the first run")
    count = len(runner.results)
    delay, elapse = await wait_for_timer()
    assert delay == pytest.approx(0.05)
    runner.pause()
    await _wait_until_pause_is_active(runner)
    elapse()
    await until(
        lambda: runner.status == "paused" and runner._pending is not None and runner._pending.done(),
        "the due fire to be held",
    )
    assert len(runner.results) == count  # nothing ran while paused

    runner.resume()
    await until(lambda: len(runner.results) > count, "a run after resume")
    await down(daemon, task)


async def test_run_now_is_the_first_way_a_manual_task_ever_runs(tmp_path):
    config = _config(tmp_path, "{type: manual}")
    daemon = Daemon(config, store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    await until(
        lambda: runner._pending is not None and not runner._pending.done(),
        "the manual trigger to arm",
    )
    assert len(runner.results) == 0  # never fires on its own

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 1, "the manual run")
    assert runner.results[0].status == "completed"
    await down(daemon, task)


async def test_run_now_on_a_paused_task_runs_once_and_stays_paused(tmp_path, monkeypatch):
    wait_for_timer = timer_barrier(monkeypatch)
    config = _config(tmp_path, "{type: interval, every: 60s, run_at_start: false}")
    daemon = Daemon(config, store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    delay, elapse = await wait_for_timer()
    assert delay == pytest.approx(60)
    runner.pause()
    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 1, "the probe run")
    await until(lambda: runner.status == "paused", "the pause to hold")
    elapse()
    await until(
        lambda: runner._pending is not None and runner._pending.done(),
        "the scheduled fire to come due",
    )
    results = await down(daemon, task)
    assert len(results) == 1  # once means once, including through shutdown


async def test_run_now_mid_run_is_refused(tmp_path):
    config = _config(tmp_path, "{type: manual}", binding=_SLOW_MOCK)
    daemon = Daemon(config, store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await until(lambda: runner.status == "running", "the run to start")
    assert runner.run_now() is False  # iterations never overlap
    assert runner._kick is False  # the refusal did not queue another fire
    await until(lambda: len(runner.results) == 1, "the run to finish")
    assert runner.status == "waiting"
    await down(daemon, task)


_JSON_GRAPH = """\
name: wants-json
entry: a
nodes:
  - {id: a, type: agent, role: r, prompt: hi, output: {format: json}}
"""

_PROSE_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "prose, not json"}}}
default: {provider: fake, model: m}
"""


async def test_a_self_paused_task_comes_back_with_resume(tmp_path):
    """The failure-causes pause used to demand a daemon restart; no longer."""
    config = _config(
        tmp_path,
        "{type: loop, max_iterations: 20}",
        binding=_PROSE_MOCK,
        graph=_JSON_GRAPH,
    )
    daemon = Daemon(config, store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    await until(lambda: runner.status == "paused", "the self-pause")
    assert len(runner.results) == 3

    runner.resume()
    # Still failing identically: three more runs, then paused again --
    # proof the failure counter started over rather than tripping at one.
    await until(
        lambda: len(runner.results) == 6 and runner.status == "paused",
        "the second self-pause",
    )
    await down(daemon, task)


async def test_shutdown_reaches_a_paused_runner_promptly(tmp_path, monkeypatch):
    wait_for_timer = timer_barrier(monkeypatch)
    config = _config(tmp_path, "{type: interval, every: 0.05s, run_at_start: false}")
    daemon = Daemon(config, store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    delay, elapse = await wait_for_timer()
    assert delay == pytest.approx(0.05)
    runner.pause()
    await _wait_until_pause_is_active(runner)
    elapse()
    await until(
        lambda: runner.status == "paused" and runner._pending is not None and runner._pending.done(),
        "the due fire to be held unrun",
    )
    results = await down(daemon, task)  # wait_for inside is the promptness check
    assert results == []
