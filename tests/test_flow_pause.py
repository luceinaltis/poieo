"""A flow that fails the same way three times pauses itself and says so."""

import asyncio
from types import SimpleNamespace

from poieo.daemon import Daemon, load_config
from poieo.daemon.service import PAUSE_AFTER, FlowRunner
from poieo.store import NullStore


# -- the counter, in isolation ------------------------------------------------


def _bare_runner():
    runner = FlowRunner.__new__(FlowRunner)
    runner._repeat_key, runner._repeat_count = None, 0
    return runner


def _failed(slug=None, error="boom"):
    cause = {"slug": slug, "said": "it broke", "fix": "fix it"} if slug else None
    return SimpleNamespace(status="failed", cause=cause, error=error)


_OK = SimpleNamespace(status="completed", cause=None, error=None)


def test_three_identical_causes_trip_the_pause():
    runner = _bare_runner()
    outcomes = [runner._note_outcome(_failed("unreachable")) for _ in range(3)]
    assert outcomes == [False, False, True]


def test_alternating_causes_never_pause():
    runner = _bare_runner()
    for i in range(10):
        slug = "unreachable" if i % 2 else "bad_output"
        assert runner._note_outcome(_failed(slug)) is False


def test_a_success_resets_the_count():
    runner = _bare_runner()
    assert runner._note_outcome(_failed("unreachable")) is False
    assert runner._note_outcome(_failed("unreachable")) is False
    assert runner._note_outcome(_OK) is False
    assert runner._note_outcome(_failed("unreachable")) is False  # back to 1


def test_unclassified_failures_count_by_their_error_text():
    runner = _bare_runner()
    outcomes = [runner._note_outcome(_failed(error="weird")) for _ in range(3)]
    assert outcomes == [False, False, True]
    runner = _bare_runner()
    assert runner._note_outcome(_failed(error="weird")) is False
    assert runner._note_outcome(_failed(error="different")) is False
    assert runner._note_outcome(_failed(error="weird")) is False


# -- the whole daemon ---------------------------------------------------------

_GRAPH = """\
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


def _config(tmp_path):
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_PROSE_MOCK, encoding="utf-8")
    path = tmp_path / "poieo.yaml"
    path.write_text(
        "binding: b.yaml\n"
        "flows:\n"
        "  - name: doomed\n"
        "    graph: g.yaml\n"
        "    trigger: {type: loop, cooldown: 0}\n",
        encoding="utf-8",
    )
    config = load_config(path)
    config.flows[0].trigger.max_iterations = 10
    return config


async def _paused(daemon, timeout=10.0):
    """Serve until the flow parks itself, then shut down and hand back results.

    A paused runner no longer ends its coroutine -- it parks and waits for
    resume -- so the daemon stays up and the test has to bring it down.
    """
    task = asyncio.create_task(daemon.serve(install_signals=False))
    deadline = asyncio.get_running_loop().time() + timeout
    while not (daemon.runners and daemon.runners[0].status == "paused"):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for the pause")
        await asyncio.sleep(0.01)
    daemon.stop()
    return await asyncio.wait_for(task, timeout=10)


async def test_an_identically_failing_flow_pauses_after_three_runs(tmp_path):
    daemon = Daemon(_config(tmp_path), store=NullStore())
    results = await _paused(daemon)
    # Three runs, not ten: the pause fired, and the fourth never did.
    assert len(results) == PAUSE_AFTER == 3
    assert daemon.runners[0].status == "paused"


async def test_a_paused_task_says_why_in_its_journal(tmp_path):
    (tmp_path / "b.yaml").write_text(
        'name: mock\n'
        'providers:\n'
        '  fake:\n'
        '    type: mock\n'
        '    options:\n'
        '      responses:\n'
        '        "*":\n'
        '          - tool_calls: [{name: list_dir, arguments: {}}]\n'
        '          - tool_calls: [{name: list_dir, arguments: {}}]\n'
        '          - tool_calls: [{name: list_dir, arguments: {}}]\n'
        'default: {provider: fake, model: m}\n',
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "doomed.yaml").write_text(
        "name: doomed\nfolder: .\nmax_turns: 1\nevery: loop\nprompt: go\n",
        encoding="utf-8",
    )
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: tasks/\n", encoding="utf-8")
    config = load_config(path)
    config.flows[0].trigger.max_iterations = 10
    config.flows[0].trigger.cooldown = 0

    daemon = Daemon(config, store=NullStore())
    await _paused(daemon)

    assert daemon.runners[0].status == "paused"
    journal = (tasks / "doomed.md").read_text(encoding="utf-8")
    # The reason survives to the next morning, beside the failures themselves.
    assert "paused after 3 identical failures" in journal
    assert "ran out of turns" in journal
    # The way back is the board, now that resume exists; a restart still works.
    assert "resume it from the board" in journal
