"""Editing a binding while the daemon runs: the next run uses it, and so does
the board.

The binding used to be parsed once at startup and held for the process
lifetime, so `poieo config use` -- or any hand edit -- reached the daemon only
by restarting it. Two things went stale together, and the second is the worse
one: tonight's run kept the old model, and `/api/tasks` kept *painting* the old
model, which is the one thing docs/web.md says the board may never do.

Design: docs/daemon.md
"""

import asyncio

import httpx

from conftest import card
from poieo.daemon import Daemon, load_config
from poieo.store import NullStore
from poieo.web import create_app

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

# The same file with the default moved -- what `poieo config use` writes.
_MOVED = _MOCK.replace("model: m1", "model: m2")


def _project(tmp_path, *, cards=("f",)):
    """A project of manual cards over one binding file.

    Manual on every card so nothing fires on its own: every run below is a
    `run_now`, which is what makes "the run after the edit" a thing a test can
    point at.
    """
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    for name in cards:
        card(tmp_path / "cards", name, "graph: ../g.yaml\ntrigger: {type: manual}\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    return load_config(path)


def _rewrite(tmp_path, text):
    (tmp_path / "b.yaml").write_text(text, encoding="utf-8")


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


async def _ran(runner, count):
    """Fire the runner by hand and wait for its nth result."""
    assert runner.run_now() is True
    await _until(lambda: len(runner.results) == count, f"run {count}")


def _asked(daemon):
    """Every model id the mocks were actually called with, in order."""
    return [
        call.model
        for pool in daemon.pools.values()
        for provider in pool.instantiated().values()
        for call in provider.calls
    ]


async def test_a_binding_edited_between_runs_is_used_by_the_next_one(tmp_path):
    daemon = Daemon(_project(tmp_path), store=NullStore())
    serving = await _up(daemon)
    runner = daemon.runners[0]

    await _ran(runner, 1)
    assert _asked(daemon) == ["m1"]

    _rewrite(tmp_path, _MOVED)
    await _ran(runner, 2)

    assert _asked(daemon) == ["m1", "m2"]
    await _down(daemon, serving)


async def test_the_board_paints_the_model_the_next_run_will_use(tmp_path):
    """The half that is easy to forget, and the one docs/web.md names.

    `_shape` resolves each node's model off the very object a run uses, so a
    daemon holding a stale spec draws a board that claims one model while its
    runs make another. On one event loop, as uvicorn shares the daemon's.
    """
    daemon = Daemon(_project(tmp_path), store=NullStore())
    serving = await _up(daemon)
    runner = daemon.runners[0]

    transport = httpx.ASGITransport(app=create_app(daemon))
    async with httpx.AsyncClient(transport=transport, base_url="http://poieo") as client:

        async def painted():
            body = (await client.get("/api/tasks")).json()
            return [node["model"] for node in body["tasks"][0]["shape"]["nodes"]]

        await _ran(runner, 1)
        assert await painted() == ["m1"]

        _rewrite(tmp_path, _MOVED)
        await _ran(runner, 2)

        assert await painted() == ["m2"]

    await _down(daemon, serving)


async def test_two_tasks_sharing_one_binding_file_are_rebound_together(tmp_path):
    """One file, one spec, however many tasks read it.

    A reread that only fixed the runner doing it would leave its siblings on
    the old spec until each happened to fire -- and the board would then paint
    a mix, which is harder to read than uniform staleness.
    """
    daemon = Daemon(_project(tmp_path, cards=("f", "g")), store=NullStore())
    serving = await _up(daemon)
    first, second = daemon.runners[0], daemon.runners[1]

    _rewrite(tmp_path, _MOVED)
    await _ran(first, 1)

    # `second` has not run at all, and is already on the new spec.
    assert not second.results
    assert second.task.binding.resolve("r").model == "m2"
    await _down(daemon, serving)


async def test_a_binding_that_will_not_parse_leaves_the_last_good_one_running(
    tmp_path, caplog
):
    """3am is no time to stop. The spec in memory is still valid and still
    what the board is claiming, so the run goes ahead on it and says why."""
    daemon = Daemon(_project(tmp_path), store=NullStore())
    serving = await _up(daemon)
    runner = daemon.runners[0]

    await _ran(runner, 1)
    _rewrite(tmp_path, "providers: {fake: {type: mock}\n  default: [")
    with caplog.at_level("WARNING", logger="poieo.daemon"):
        await _ran(runner, 2)

    assert _asked(daemon) == ["m1", "m1"]
    assert runner.results[1].status == "completed"
    assert "b.yaml" in caplog.text
    await _down(daemon, serving)


async def test_a_reread_that_cannot_resolve_a_role_is_not_adopted(tmp_path):
    """It parses, and it would still have been refused at startup.

    `load_tasks` will not arm a task whose roles do not resolve, so a file
    saved mid-flight must not put the daemon somewhere it would have declined
    to start.
    """
    daemon = Daemon(_project(tmp_path), store=NullStore())
    serving = await _up(daemon)
    runner = daemon.runners[0]

    # Parses fine; declares no default, so role 'r' resolves to nothing.
    _rewrite(
        tmp_path,
        "name: mock\nproviders:\n  fake: {type: mock, options: {responses: {'*': done}}}\n"
        "roles:\n  other: {provider: fake, model: m2}\n",
    )
    await _ran(runner, 1)

    assert _asked(daemon) == ["m1"]
    assert runner.results[0].status == "completed"
    await _down(daemon, serving)


async def test_a_reread_that_needs_a_key_that_is_not_set_is_not_adopted(
    tmp_path, monkeypatch
):
    """The other startup check, applied to the same moment."""
    monkeypatch.delenv("POIEO_TEST_KEY", raising=False)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    serving = await _up(daemon)
    runner = daemon.runners[0]

    _rewrite(
        tmp_path,
        "name: mock\nproviders:\n  fake: {type: mock, api_key_env: POIEO_TEST_KEY, "
        "options: {responses: {'*': done}}}\ndefault: {provider: fake, model: m2}\n",
    )
    await _ran(runner, 1)

    # Adopted, the run would have died building a provider it cannot open --
    # so the status is the assertion, not the call count.
    assert runner.results[0].status == "completed"
    assert _asked(daemon) == ["m1"]
    await _down(daemon, serving)


async def test_the_pool_keeps_its_clients_when_only_a_role_moved(tmp_path):
    """The claim that makes the small change correct.

    A pool caches one client per provider *name*, built from that provider's
    own block; the model id never enters it and travels per request. Moving a
    role rewrites `default:`/`roles:` and leaves `providers:` byte-identical,
    so there is nothing to close and nothing to rebuild.
    """
    daemon = Daemon(_project(tmp_path), store=NullStore())
    serving = await _up(daemon)
    runner = daemon.runners[0]

    await _ran(runner, 1)
    pool = daemon.pools[runner.task.binding_key]
    before = pool.instantiated()["fake"]

    _rewrite(tmp_path, _MOVED)
    await _ran(runner, 2)

    assert pool.instantiated()["fake"] is before
    assert _asked(daemon) == ["m1", "m2"]
    await _down(daemon, serving)


async def test_a_newly_declared_endpoint_is_reachable_without_a_restart(tmp_path):
    """What `poieo config add` writes, seen by a daemon that is already up.

    This is the case the pool's own reference to the spec is for: `get()`
    looks a provider up in the binding it was built with, so a role pointed at
    an endpoint declared after startup would have been "not declared".
    """
    daemon = Daemon(_project(tmp_path), store=NullStore())
    serving = await _up(daemon)
    runner = daemon.runners[0]

    await _ran(runner, 1)
    _rewrite(
        tmp_path,
        "name: mock\nproviders:\n"
        "  fake: {type: mock, options: {responses: {'*': done}}}\n"
        "  later: {type: mock, options: {responses: {'*': done}}}\n"
        "default: {provider: later, model: m2}\n",
    )
    await _ran(runner, 2)

    pool = daemon.pools[runner.task.binding_key]
    assert "later" in pool.instantiated()
    assert _asked(daemon) == ["m1", "m2"]
    await _down(daemon, serving)
