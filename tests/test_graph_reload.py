"""Editing what a task *does* while the daemon runs: the next run does it.

The binding has been re-read before every run since the board started painting
which model would answer. The graph was not -- so a prompt edited at noon, by a
hand or by the board, waited for a restart while the daemon carried on running
the words it had read at breakfast.

DESIGN.md has promised otherwise the whole time: "Edits are saved to files and
picked up by the daemon from the next run. No restarts."

Design: docs/daemon.md
"""

import asyncio

from conftest import card

from poieo.daemon import Daemon, load_config
from poieo.store import NullStore

_GRAPH = """\
name: quick
entry: a
nodes:
  - {id: a, type: agent, role: r, prompt: first}
"""

_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "done"}}}
default: {provider: fake, model: m1}
"""


def _project(tmp_path):
    """One manual card over one graph file, so every run below is a `run_now`
    and "the run after the edit" is a thing a test can point at."""
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    card(tmp_path / "cards", "f", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    return load_config(path)


def _prompts(daemon):
    """Every prompt the mocks were actually asked, in order."""
    return [
        message.get("content", "")
        for pool in daemon.pools.values()
        for provider in pool.instantiated().values()
        for call in provider.calls
        for message in call.messages
    ]


async def _up(daemon):
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


async def test_a_graph_edited_between_runs_is_used_by_the_next_one(tmp_path):
    """The whole promise, in one file and two runs."""
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await _until(lambda: len(runner.results) == 1, "the first run")

    (tmp_path / "g.yaml").write_text(_GRAPH.replace("prompt: first", "prompt: second"), encoding="utf-8")

    assert runner.run_now() is True
    await _until(lambda: len(runner.results) == 2, "the run after the edit")

    asked = _prompts(daemon)
    assert "first" in asked[0]
    assert "second" in asked[-1], f"the edit was not picked up: {asked}"

    await _down(daemon, task)


def _card_project(tmp_path):
    """A card carrying its own prompt -- no graph file at all, which is the
    shape the board will write and the one a person actually edits."""
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "work").mkdir(exist_ok=True)
    card(
        tmp_path / "cards",
        "f",
        "folder: ../work\nprompt: first\ntrigger: {type: manual}\n",
    )
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    return load_config(path)


async def test_a_cards_own_prompt_is_re_read_too(tmp_path):
    """The card is the file a person writes, so it is the one that must not
    need a restart. It carries no graph, so the re-read has to re-expand it."""
    daemon = Daemon(_card_project(tmp_path), store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await _until(lambda: len(runner.results) == 1, "the first run")

    card(tmp_path / "cards", "f", "folder: ../work\nprompt: second\ntrigger: {type: manual}\n")

    assert runner.run_now() is True
    await _until(lambda: len(runner.results) == 2, "the run after the edit")

    asked = " ".join(_prompts(daemon))
    assert "second" in asked, f"the card edit was not picked up: {asked}"

    await _down(daemon, task)


async def test_a_graph_that_will_not_parse_leaves_the_last_good_one_running(tmp_path, caplog):
    """3am is no time to stop working over a file saved half-written. The run
    goes ahead on what is already in memory, and says so."""
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await _up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await _until(lambda: len(runner.results) == 1, "the first run")

    (tmp_path / "g.yaml").write_text("nodes: [", encoding="utf-8")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        assert runner.run_now() is True
        await _until(lambda: len(runner.results) == 2, "the run after the bad save")

    # Both halves: it kept working, and it did not keep quiet about why.
    assert "first" in _prompts(daemon)[-1]
    assert any("last good one" in message for message in caplog.messages), caplog.messages

    await _down(daemon, task)
