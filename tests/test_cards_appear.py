"""A card written while the daemon runs starts running.

Until now the tasks folder was read once, at startup. A card added after that
sat there doing nothing until somebody restarted the daemon -- which is the
last thing a board that can create tasks may ask of the person using it, and
the reason DESIGN.md's roadmap says the daemon gains add at runtime.

Design: docs/daemon.md
"""

import asyncio

import httpx
import pytest
from conftest import card, down, until, up

from poieo.daemon import Daemon, load_config
from poieo.store import NullStore
from poieo.web import create_app

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
default: {provider: fake, model: m1}
"""


def _project(tmp_path):
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    card(tmp_path / "cards", "first", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    return load_config(path)


def _named(daemon, name):
    return next((r for r in daemon.runners if r.name == name), None)


async def test_a_card_written_while_the_daemon_runs_starts_running(tmp_path, monkeypatch):
    """The whole slice, in one file appearing."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)
    assert [r.name for r in daemon.runners] == ["first"]

    card(tmp_path / "cards", "second", "graph: ../g.yaml\ntrigger: {type: manual}\n")

    await until(lambda: _named(daemon, "second") is not None, "the new card to be noticed")
    added = _named(daemon, "second")

    # Noticed is not running. It has to be able to take a kick and finish one.
    assert added.run_now() is True
    await until(lambda: len(added.results) == 1, "the new card's first run")
    assert added.results[-1].status == "completed"

    await down(daemon, task)


async def test_a_card_saved_half_written_does_not_take_the_others_down(tmp_path, monkeypatch, caplog):
    """The same rule the binding and the graph follow. A folder that will not
    load is a warning: the tasks that have run all night beside it keep going,
    and the daemon says why nothing new started."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        (tmp_path / "cards" / "broken.yaml").write_text("name: [", encoding="utf-8")
        await until(
            lambda: any("nothing new starts" in m for m in caplog.messages),
            "the daemon to say it could not read the folder",
        )

    # The one that was already running still is, and still works.
    running = _named(daemon, "first")
    assert running is not None
    assert running.run_now() is True
    await until(lambda: len(running.results) == 1, "the surviving task's run")

    await down(daemon, task)


async def test_the_daemon_still_comes_down_with_a_task_it_grew(tmp_path, monkeypatch):
    """The risk this loop introduces. `serve` waits on the runners it built at
    startup; one started later is held by the watcher instead, so shutdown has
    to reach it there. If it does not, the daemon hangs on the way down -- the
    one failure a resident process may never have."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)

    card(tmp_path / "cards", "late", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    await until(lambda: _named(daemon, "late") is not None, "the new card")

    # Never kicked, so it is parked waiting for a trigger that will not come:
    # exactly the state a task is in at 3am when somebody stops the daemon.
    await asyncio.wait_for(down(daemon, task), timeout=15)


async def test_a_card_whose_filename_is_its_identity(tmp_path, monkeypatch):
    """`name:` is a title and rewritable; the filename is what the task is
    called. Worth pinning here because the watcher decides what is new by that
    name, and a card retitled at noon must not read as a second task."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)

    card(tmp_path / "cards", "later", "name: a title\ngraph: ../g.yaml\ntrigger: {type: manual}\n")
    await until(lambda: len(daemon.runners) == 2, "the new card")

    assert sorted(r.name for r in daemon.runners) == ["first", "later"]

    await down(daemon, task)


async def test_a_daemon_with_nothing_to_run_still_watches(tmp_path, monkeypatch):
    """The case the board exists for. `poieo daemon` on a project whose tasks
    folder is empty used to warn and stop, so the first card written from the
    browser would have had nowhere to land."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "cards").mkdir()
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")

    daemon = Daemon(load_config(path), store=NullStore())
    serving = await up(daemon, wait_for_runners=False)
    await asyncio.sleep(0.1)
    assert not serving.done(), "the daemon stopped instead of waiting for a card"

    card(tmp_path / "cards", "born", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    await until(lambda: _named(daemon, "born") is not None, "the first card ever")

    await down(daemon, serving)


async def test_a_card_asking_for_isolation_waits_for_a_restart(tmp_path, monkeypatch, caplog):
    """Refused rather than half-given, the rule the graph reread follows. The
    container keeper is built from the startup task set, so an isolated card
    noticed at noon would run with none -- rebuilding a throwaway container
    every run while believing it was fenced."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    # The refusal is the thing under test, not whether this machine has docker
    # and that image. Left real, the load fails first on a runner without them
    # and the card is refused for the wrong reason -- which is how this passed
    # here and failed on all three CI legs.
    monkeypatch.setattr("poieo.daemon.config.check_isolation", lambda tasks: None)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        card(
            tmp_path / "cards",
            "fenced",
            "graph: ../g.yaml\ntrigger: {type: manual}\nisolation: {image: alpine:3.20}\n",
        )
        await until(
            lambda: any("asks for isolation" in m for m in caplog.messages),
            "the daemon to refuse it",
        )

    assert _named(daemon, "fenced") is None

    await down(daemon, task)


async def test_a_card_posted_to_the_board_starts_running(tmp_path, monkeypatch):
    """The two halves meeting, which is the only thing neither test proves on
    its own: the route writes a file, and the daemon that was already running
    picks it up. No reload call between them -- one door, and the daemon finds
    a card written by a browser the same way it finds one written by a hand."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    (tmp_path / "work").mkdir()
    daemon = Daemon(_project(tmp_path), store=NullStore())
    serving = await up(daemon)

    transport = httpx.ASGITransport(app=create_app(daemon))
    async with httpx.AsyncClient(transport=transport, base_url="http://poieo") as client:
        answer = await client.post(
            f"/api/projects/{daemon.config.display_name}/tasks",
            json={"name": "from the board", "folder": "../work", "prompt": "look around"},
        )
        assert answer.status_code == 200, answer.text

        await until(
            lambda: _named(daemon, "from-the-board") is not None,
            "the posted card to start running",
        )
        # And it is a task, not just a name in a list. It fires on its own --
        # a card takes `every: 1h` and runs at start -- so kicking it here
        # would race that first firing and be refused mid-run some of the time.
        made = _named(daemon, "from-the-board")
        await until(lambda: len(made.results) == 1, "the run it starts itself")
        assert made.results[-1].status == "completed"

    await down(daemon, serving)
