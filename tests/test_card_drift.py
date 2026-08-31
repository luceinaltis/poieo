"""A card edited by hand that the running task cannot become says so.

Only a card's prompt is really re-read before a run. A schedule, a folder, an
`enabled:` or an `isolation:` reaches a trigger that was built when the daemon
started, so the daemon refuses to half-adopt the change -- and until now said
so in one `log.warning`, at the next firing, into a terminal nobody is reading.
A card edited at noon whose task fires at 3am kept its old schedule all day
with nothing anywhere to say so.

The folder is already re-read every few seconds for cards that appeared. This
is the same scan answering the other question: of the cards that were already
here, which no longer describe what is running.

Design: docs/daemon.md
"""

import asyncio

from conftest import card, down, until, up

from poieo.daemon import Daemon, load_config
from poieo.store import NullStore
from poieo.web import BroadcastStore

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


# On a cron rather than an interval, for the one test that watches the feed: an
# interval card fires the moment it is armed, and its run events would be what
# arrived first.
_AT_THREE = 'folder: .\nprompt: look around\nat: "0 3 * * *"\n'
_AT_FOUR = 'folder: .\nprompt: look around\nat: "0 4 * * *"\n'


def _project(tmp_path, body="folder: .\nprompt: look around\nevery: 1h\n"):
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "work").mkdir()
    card(tmp_path / "cards", "chores", body)
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    return load_config(path)


def _named(daemon, name):
    return next((r for r in daemon.runners if r.name == name), None)


async def test_a_schedule_edited_by_hand_is_reported_on_the_task(tmp_path, monkeypatch):
    """The one the whole file is for: a schedule cannot reach a built trigger,
    so the reader has to be told rather than left believing the edit took."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)
    assert _named(daemon, "chores").stale is None

    card(tmp_path / "cards", "chores", "folder: .\nprompt: look around\nevery: 30m\n")

    await until(lambda: _named(daemon, "chores").stale is not None, "the edit to be noticed")
    assert "restart" in _named(daemon, "chores").stale
    await down(daemon, task)


async def test_an_edited_prompt_is_not_reported(tmp_path, monkeypatch):
    """The half a run really does adopt. Warning about it would teach the
    reader to ignore the warning, which costs the schedule case its whole
    value."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)

    card(tmp_path / "cards", "chores", "folder: .\nprompt: look somewhere else\nevery: 1h\n")

    # Nothing to wait on, so wait out several scans and assert on the silence.
    await asyncio.sleep(0.3)
    assert _named(daemon, "chores").stale is None
    await down(daemon, task)


async def test_putting_the_card_back_clears_it(tmp_path, monkeypatch):
    """A warning that cannot be cleared is a warning a reader stops seeing."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)

    card(tmp_path / "cards", "chores", "folder: .\nprompt: look around\nevery: 30m\n")
    await until(lambda: _named(daemon, "chores").stale is not None, "the edit to be noticed")

    card(tmp_path / "cards", "chores", "folder: .\nprompt: look around\nevery: 1h\n")
    await until(lambda: _named(daemon, "chores").stale is None, "the edit to be undone")
    await down(daemon, task)


async def test_a_card_that_will_not_load_says_so_on_its_own_task(tmp_path, monkeypatch):
    """The worst case, and the one the folder scan used to answer with silence:
    a typo made the whole folder unreadable, so the scan gave up before it
    reached the card -- and nothing new started either, which is a second thing
    the reader was not told."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)

    card(tmp_path / "cards", "chores", "folder: .\npromt: look around\n")

    await until(lambda: _named(daemon, "chores").stale is not None, "the broken card to be noticed")
    assert "promt" in _named(daemon, "chores").stale
    await down(daemon, task)


async def test_the_board_is_told_to_read_again(tmp_path, monkeypatch):
    """The board reads `/api/tasks` when it opens and when the feed reconnects,
    and nothing else -- so a card edited under an open page reached nobody. The
    daemon says "ask again"; the frame carries no detail because the read is
    the detail.

    On a cron, so the only thing on the feed is the announcement itself.
    """
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    daemon = Daemon(_project(tmp_path, _AT_THREE), store=BroadcastStore(NullStore()))
    task = await up(daemon)
    queue = daemon.projects[0].store.subscribe()

    card(tmp_path / "cards", "chores", _AT_FOUR)
    await until(lambda: not queue.empty(), "the board to be told")

    assert queue.get_nowait()["type"] == "tasks_changed"

    # And said once: a frame every five seconds over a file nobody has touched
    # since lunch is how a reader learns to ignore the feed.
    await asyncio.sleep(0.3)
    assert queue.empty()
    await down(daemon, task)


async def test_a_card_naming_its_own_graph_is_judged_too(tmp_path, monkeypatch):
    """The shape the first cut of this passed over. A card with a `graph:` of
    its own hands back no generated graph, and that was read as "nothing to
    compare" -- so a schedule edited on one of those was ignored *and* silent,
    which is the exact pair this exists to break up."""
    monkeypatch.setattr("poieo.daemon.service.SCAN_SECONDS", 0.05)
    (tmp_path / "g.yaml").write_text(
        "name: quick\nentry: a\nnodes:\n  - {id: a, type: agent, role: r, prompt: hi}\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    card(tmp_path / "cards", "chores", 'graph: ../g.yaml\nat: "0 3 * * *"\n')
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    daemon = Daemon(load_config(path), store=NullStore())
    task = await up(daemon)
    assert _named(daemon, "chores").stale is None

    card(tmp_path / "cards", "chores", 'graph: ../g.yaml\nat: "0 4 * * *"\n')

    await until(lambda: _named(daemon, "chores").stale is not None, "the edit to be noticed")
    assert "restart" in _named(daemon, "chores").stale
    await down(daemon, task)
