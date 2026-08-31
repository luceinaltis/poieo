"""Editing what a task *does* while the daemon runs: the next run does it.

The binding has been re-read before every run since the board started painting
which model would answer. The graph was not -- so a prompt edited at noon, by a
hand or by the board, waited for a restart while the daemon carried on running
the words it had read at breakfast.

DESIGN.md has promised otherwise the whole time: "Edits are saved to files and
picked up by the daemon from the next run. No restarts."

Design: docs/daemon.md
"""

import logging
from contextlib import contextmanager

from conftest import card, down, until, up

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


async def test_a_graph_edited_between_runs_is_used_by_the_next_one(tmp_path):
    """The whole promise, in one file and two runs."""
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 1, "the first run")

    (tmp_path / "g.yaml").write_text(_GRAPH.replace("prompt: first", "prompt: second"), encoding="utf-8")

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 2, "the run after the edit")

    asked = _prompts(daemon)
    assert "first" in asked[0]
    assert "second" in asked[-1], f"the edit was not picked up: {asked}"

    await down(daemon, task)


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
    task = await up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 1, "the first run")

    card(tmp_path / "cards", "f", "folder: ../work\nprompt: second\ntrigger: {type: manual}\n")

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 2, "the run after the edit")

    asked = " ".join(_prompts(daemon))
    assert "second" in asked, f"the card edit was not picked up: {asked}"

    await down(daemon, task)


async def test_a_graph_that_will_not_parse_leaves_the_last_good_one_running(tmp_path, caplog):
    """3am is no time to stop working over a file saved half-written. The run
    goes ahead on what is already in memory, and says so."""
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 1, "the first run")

    (tmp_path / "g.yaml").write_text("nodes: [", encoding="utf-8")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        assert runner.run_now() is True
        await until(lambda: len(runner.results) == 2, "the run after the bad save")

    # Both halves: it kept working, and it did not keep quiet about why.
    assert "first" in _prompts(daemon)[-1]
    assert any("last good one" in message for message in caplog.messages), caplog.messages

    await down(daemon, task)


@contextmanager
def caplog_at_warning():
    """caplog with a live list: the assertion reads it after the block."""
    messages: list[str] = []

    class _Sink(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger, sink = logging.getLogger("poieo.daemon"), _Sink()
    logger.addHandler(sink)
    try:
        yield messages
    finally:
        logger.removeHandler(sink)


async def test_a_card_that_changed_more_than_its_prompt_is_refused(tmp_path):
    """A card expands into a spec *and* a graph, and they split fields a reader
    would call one thing. Adopting the graph alone would honour new `tools:`
    while ignoring the `isolation:` asked for in the same edit -- shell on the
    host rather than in a container. So the whole edit waits for a restart."""
    daemon = Daemon(_card_project(tmp_path), store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 1, "the first run")

    (tmp_path / "elsewhere").mkdir()
    card(
        tmp_path / "cards",
        "f",
        "folder: ../elsewhere\nprompt: second\ntrigger: {type: manual}\n",
    )

    with caplog_at_warning() as messages:
        assert runner.run_now() is True
        await until(lambda: len(runner.results) == 2, "the run after the edit")

    # The prompt moved with the folder, so taking one without the other would
    # tell the model it works somewhere the tools are not rooted.
    assert "second" not in " ".join(_prompts(daemon))
    assert any("more than its prompt" in m for m in messages), messages

    await down(daemon, task)


async def test_a_broken_binding_does_not_freeze_the_graphs_reread(tmp_path):
    """Two files, two failures. One saved half-written must not quietly stop
    the other from being read -- which is what a single raise for both did."""
    daemon = Daemon(_project(tmp_path), store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 1, "the first run")

    (tmp_path / "b.yaml").write_text("providers: [", encoding="utf-8")
    (tmp_path / "g.yaml").write_text(_GRAPH.replace("prompt: first", "prompt: second"), encoding="utf-8")

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 2, "the run after both saves")

    assert "second" in _prompts(daemon)[-1], "the graph waited on the binding"

    await down(daemon, task)


_KEYED = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "done"}}}
  keyed: {type: openai_compatible, base_url: 'http://x/v1', api_key_env: POIEO_RELOAD_KEY}
default: {provider: fake, model: m1}
roles:
  reviewer: {provider: keyed, model: m}
"""


async def test_a_graph_naming_a_role_with_no_key_is_refused(tmp_path, monkeypatch):
    """The reread runs both checks startup runs, not one.

    A graph edited to reach a role whose key is unset would otherwise be
    adopted, die opening the provider, and then make every later binding
    reread raise on the roles it had just added -- a task stuck until restart
    by a file it read itself.
    """
    monkeypatch.delenv("POIEO_RELOAD_KEY", raising=False)
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_KEYED, encoding="utf-8")
    card(tmp_path / "cards", "f", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")

    daemon = Daemon(load_config(path), store=NullStore())
    task = await up(daemon)
    runner = daemon.runners[0]

    assert runner.run_now() is True
    await until(lambda: len(runner.results) == 1, "the first run")

    (tmp_path / "g.yaml").write_text(_GRAPH.replace("role: r", "role: reviewer"), encoding="utf-8")

    with caplog_at_warning() as messages:
        assert runner.run_now() is True
        await until(lambda: len(runner.results) == 2, "the run after the edit")

    assert runner.results[-1].status == "completed", "the run should have gone ahead"
    assert any("POIEO_RELOAD_KEY" in m for m in messages), messages

    await down(daemon, task)
