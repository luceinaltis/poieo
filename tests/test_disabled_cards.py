"""A card that is switched off is on the board, switched off.

Until now `enabled: false` meant the daemon built no runner at all, so the card
was not merely stopped -- it was *invisible*. The one thing a person could not
find out from the board was that a task they wrote exists and is not running,
which is the question the board is for. Setting one aside already answers it
the other way: the task stays on the board, paused, until a restart.

So a disabled card gets a runner that is held, and the board draws it beside
the rest. Held **harder** than the pause button holds, though: a pause is
runtime state a run-now or a handoff is allowed to win over, and `enabled:
false` is a durable off switch written in a file. Nothing at runtime may
override it -- or a handoff would quietly start the task somebody switched off,
while the file went on saying otherwise.

Design: docs/daemon.md
"""

import asyncio

import pytest
from conftest import card, down, until, up

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
default: {provider: fake, model: m1}
"""


# Something armed to keep the daemon standing. A project of nothing but
# switched-off cards has nothing to wait for and `serve()` returns at once,
# which is right -- and is not what these tests are looking at.
_STANDING = {"standing": "graph: ../g.yaml\ntrigger: {type: manual}\n"}

# A schedule: the kind of edit a scan may *not* adopt, whatever else is in the
# same save.
_AT_THREE = 'graph: ../g.yaml\nat: "0 3 * * *"\n'
_AT_FOUR = 'graph: ../g.yaml\nat: "0 4 * * *"\n'


def _project(tmp_path, cards):
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    for name, body in {**_STANDING, **cards}.items():
        card(tmp_path / "cards", name, body)
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    return load_config(path)


def _named(daemon, name):
    return next((r for r in daemon.runners if r.name == name), None)


async def test_a_switched_off_card_is_on_the_board(tmp_path):
    """The whole point: it was not there at all, and now it is -- stopped."""
    daemon = Daemon(_project(tmp_path, {"sleeper": "graph: ../g.yaml\nenabled: false\n"}), store=NullStore())
    task = await up(daemon)

    runner = _named(daemon, "sleeper")
    assert runner is not None
    assert runner.status == "paused"
    assert runner.armed is False
    await down(daemon, task)


async def test_it_stays_stopped_however_it_is_asked(tmp_path):
    """A pause is runtime state, and a run-now is allowed to win over one.
    This is not a pause -- it is a file saying no, and a button on a page may
    not overrule a file."""
    daemon = Daemon(_project(tmp_path, {"sleeper": "graph: ../g.yaml\nenabled: false\n"}), store=NullStore())
    task = await up(daemon)
    runner = _named(daemon, "sleeper")

    assert runner.run_now() is False
    # Several ticks of the loop, so a fire that was going to happen has had
    # every chance to.
    await asyncio.sleep(0.2)
    assert len(runner.results) == 0
    assert runner.status == "paused"
    await down(daemon, task)


async def test_a_handoff_cannot_start_one(tmp_path):
    """The hazard the whole distinction exists for. A `then:` that reaches a
    switched-off task used to find no runner at all; with a runner there to
    find, an unguarded kick would start it -- a kick wins over a hold -- and
    `enabled: false` would have quietly stopped meaning anything.

    Silently passed over, as it always was: `check_handoffs` says it once at
    load, and saying it again on every run is noise."""
    daemon = Daemon(
        _project(
            tmp_path,
            {
                "sender": 'graph: ../g.yaml\ntrigger: {type: manual}\nthen:\n  - when: "True"\n    to: receiver\n',
                "receiver": "graph: ../g.yaml\nenabled: false\n",
            },
        ),
        store=NullStore(),
    )
    task = await up(daemon)
    receiver = _named(daemon, "receiver")

    _named(daemon, "sender").run_now()
    await until(lambda: _named(daemon, "sender").results, "the sender to finish")
    await asyncio.sleep(0.2)

    assert len(receiver.results) == 0
    assert receiver.status == "paused"
    await down(daemon, task)


async def test_switching_one_on_in_its_file_arms_it(tmp_path, monkeypatch):
    """The other half of the switch, and the reason the board may write it.

    `enabled:` is the one field a scan can adopt whole: the task is not
    mid-run either way, so a fresh runner built from the file is a full
    adoption rather than the half-adoption `_reread_graph` refuses. Anything
    else in the card still wants a restart.
    """
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(
        _project(tmp_path, {"sleeper": "graph: ../g.yaml\ntrigger: {type: manual}\nenabled: false\n"}),
        store=NullStore(),
    )
    task = await up(daemon)
    assert _named(daemon, "sleeper").armed is False

    card(tmp_path / "cards", "sleeper", "graph: ../g.yaml\ntrigger: {type: manual}\nenabled: true\n")

    await until(lambda: _named(daemon, "sleeper").armed, "the task to be armed")
    # Armed means it takes a kick, which is the whole of what being on means.
    assert _named(daemon, "sleeper").run_now() is True
    await until(lambda: _named(daemon, "sleeper").results, "the run it was asked for")
    # And nothing is left saying the file and the daemon disagree.
    assert _named(daemon, "sleeper").stale is None
    await down(daemon, task)


async def test_switching_one_off_in_its_file_stops_it(tmp_path, monkeypatch):
    """Both halves, the way setting a task aside does them: the file is the
    durable one, and the schedule stops now rather than firing all night
    against a card that says not to."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(
        _project(tmp_path, {"sleeper": "graph: ../g.yaml\ntrigger: {type: manual}\n"}),
        store=NullStore(),
    )
    task = await up(daemon)
    assert _named(daemon, "sleeper").armed is True

    card(tmp_path / "cards", "sleeper", "graph: ../g.yaml\ntrigger: {type: manual}\nenabled: false\n")

    await until(lambda: not _named(daemon, "sleeper").armed, "the task to be switched off")
    assert _named(daemon, "sleeper").status == "paused"
    assert _named(daemon, "sleeper").run_now() is False
    assert _named(daemon, "sleeper").stale is None
    await down(daemon, task)


async def test_anything_else_in_the_card_still_wants_a_restart(tmp_path, monkeypatch):
    """The line that keeps this from being "the scan adopts edits now". A
    schedule reaches a trigger built at startup, and rebuilding a runner
    around one is not the same as adopting it -- a task mid-run would lose
    what it was doing."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path, {"sleeper": _AT_THREE}), store=NullStore())
    task = await up(daemon)

    card(tmp_path / "cards", "sleeper", _AT_FOUR)

    await until(lambda: _named(daemon, "sleeper").stale is not None, "the edit to be noticed")
    assert "restart" in _named(daemon, "sleeper").stale
    await down(daemon, task)
