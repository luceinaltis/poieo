"""A task is one file that expands into a task plus a one-node graph.

The expansion tests compare against the hand-written equivalent on purpose:
that equality is the whole safety argument for the sugar.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from conftest import at

from poieo.card import (
    DEFAULT_MAX_TURNS,
    CardSpec,
    append_journal,
    expand,
    is_card_document,
    load_card,
    load_cards,
    read_journal,
    system_block,
)
from poieo.daemon.config import TaskSpec, check_handoffs, load_config, load_tasks
from poieo.errors import SpecError
from poieo.graph import GraphSpec
from poieo.memory import write_page
from poieo.store import NullStore

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def write_card(root: Path, stem: str, body: str, folder: Path | None = None) -> Path:
    """A task file in <root>/tasks, with its folder created."""
    target = folder or (root / "project")
    target.mkdir(parents=True, exist_ok=True)
    tasks = root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    path = tasks / f"{stem}.yaml"
    path.write_text(f"folder: {target.as_posix()}\n{body}", encoding="utf-8")
    return path


# -- expansion ---------------------------------------------------------------


def test_expansion_equals_the_hand_written_flow_and_graph(tmp_path):
    path = write_card(
        tmp_path,
        "keep-improving",
        "name: keep improving poieo\nprompt: |\n  Fix one thing.\n",
    )
    task, graph = expand(load_card(path))

    assert task == TaskSpec(
        name="keep-improving",
        graph=str(path),
        trigger={"type": "interval", "every": "1h"},
        # The folder lands on the task, which is what opens a private copy of
        # it. On the node it would only have said where to write.
        workdir=str(tmp_path / "project"),
        carry_state=True,
    )
    assert graph == GraphSpec(
        name="keep-improving",
        description="keep improving poieo",
        entry="work",
        nodes=[
            {
                "id": "work",
                "type": "agent",
                "tools": ["files", "shell"],
                "max_turns": 40,
                "system": graph.nodes[0].system,
                "prompt": "Fix one thing.\n",
                "output": {"as": "summary"},
            }
        ],
    )


def test_the_generated_prompt_asks_for_a_one_line_summary(tmp_path):
    path = write_card(tmp_path, "t", "name: tidy up\nprompt: go\n")
    _, graph = expand(load_card(path))
    assert "one line" in graph.nodes[0].system
    assert "tidy up" in graph.nodes[0].system


def test_optional_keys_land_on_the_node(tmp_path):
    path = write_card(
        tmp_path,
        "t",
        "name: t\nprompt: go\nrole: worker\ntools: [files]\nmax_turns: 5\n",
    )
    _, graph = expand(load_card(path))
    node = graph.nodes[0]
    assert (node.role, node.tools, node.max_turns) == ("worker", ["files"], 5)


def test_a_card_that_names_no_tools_gets_the_one_default_toolset(tmp_path):
    """The card's default and the agent node's default are one constant.

    They used to be two lists spelled the same in two modules, which is a
    thing that stays true right up until it doesn't.
    """
    from poieo.tools import DEFAULT_TOOLSETS

    _, graph = expand(load_card(write_card(tmp_path, "t", "name: t\nprompt: go\n")))
    assert graph.nodes[0].tools == DEFAULT_TOOLSETS


@pytest.mark.parametrize(
    "body, expected",
    [
        ("name: t\nprompt: go\n", {"type": "interval", "every": "1h"}),
        ("name: t\nprompt: go\nevery: 30m\n", {"type": "interval", "every": "30m"}),
        ("name: t\nprompt: go\nevery: loop\n", {"type": "loop"}),
        ("name: t\nprompt: go\nat: '0 3 * * *'\n", {"type": "cron"}),
    ],
)
def test_schedule_sugar(tmp_path, body, expected):
    task, _ = expand(load_card(write_card(tmp_path, "t", body)))
    assert task.trigger.type == expected["type"]
    if "every" in expected:
        assert task.trigger.every == expected["every"]


def test_identity_comes_from_the_filename_not_the_title(tmp_path):
    path = write_card(tmp_path, "keep-improving", "name: a title I will rewrite\nprompt: go\n")
    task, graph = expand(load_card(path))
    assert task.name == "keep-improving"
    assert graph.name == "keep-improving"


def test_an_ejected_task_names_its_graph_instead_of_generating_one(tmp_path):
    graphs = tmp_path / "graphs"
    graphs.mkdir()
    (graphs / "t.yaml").write_text(
        "name: t\nentry: a\nnodes:\n  - {id: a, type: agent, prompt: hi}\n", encoding="utf-8"
    )
    path = write_card(tmp_path, "t", "name: t\ngraph: ../graphs/t.yaml\n")
    task, graph = expand(load_card(path))
    assert graph is None
    assert Path(task.graph) == (graphs / "t.yaml").resolve()


# -- cards and graphs share a folder -----------------------------------------
#
# A card is a graph's short form, so the two are one kind of thing -- what a
# person writes -- and live together. Which is which is a question the
# document answers: a card has a folder, a graph has nodes.


def write_graph(root: Path, stem: str) -> Path:
    tasks = root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    path = tasks / f"{stem}.graph.yaml"
    path.write_text("name: g\nentry: a\nnodes:\n  - {id: a, type: agent, prompt: hi}\n", encoding="utf-8")
    return path


def test_a_graph_beside_a_card_is_not_read_as_a_card(tmp_path):
    write_card(tmp_path, "tidy", "name: tidy\nprompt: go\n")
    write_graph(tmp_path, "tidy")
    assert [task.slug for task in load_cards(tmp_path / "tasks")] == ["tidy"]


def test_a_file_that_says_nothing_useful_is_told_what_a_card_needs(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "confused.yaml").write_text("name: neither\nversion: 1\n", encoding="utf-8")
    with pytest.raises(SpecError) as caught:
        load_cards(tasks)
    # Read as the card it nearly is, and told which key is the problem --
    # which beats "this is neither shape" for anyone holding the file.
    assert "version" in str(caught.value)


def test_a_file_answering_to_both_shapes_fails_rather_than_disappearing(tmp_path):
    """A card that grew a `nodes:` key answers to no rule. Reading it as a
    graph would drop a task from the roster without a word."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "both.yaml").write_text("name: both\nfolder: .\nnodes:\n  - {id: a, type: agent}\n", encoding="utf-8")
    with pytest.raises(SpecError):
        load_cards(tasks)


def test_a_card_whose_yaml_is_broken_still_fails_the_load(tmp_path):
    """The trap this folder invites: sorting cards from graphs by *trying* to
    parse would turn a typo into a silently absent task -- a card that stops
    running at 3am with nothing said. It fails here instead."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "broken.yaml").write_text("name: broken\n  folder: .\n", encoding="utf-8")
    with pytest.raises(SpecError):
        load_cards(tasks)


def test_a_card_with_an_unknown_key_still_fails_the_load(tmp_path):
    write_card(tmp_path, "tidy", "name: tidy\nprompt: go\nbogus: 1\n")
    with pytest.raises(SpecError):
        load_cards(tmp_path / "tasks")


def test_paths_resolve_against_the_task_file(tmp_path):
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "here").mkdir()
    path = tmp_path / "tasks" / "t.yaml"
    path.write_text("name: t\nfolder: here\nprompt: go\n", encoding="utf-8")
    task, graph = expand(load_card(path))

    assert task.workdir == str(tmp_path / "tasks" / "here")
    # And nowhere on the node: the run is handed a private copy of that folder,
    # and a node that named the real one would write straight past it.
    assert graph.nodes[0].workdir is None


# -- refusals ----------------------------------------------------------------


@pytest.mark.parametrize(
    "body, message",
    [
        ("name: t\n", "needs a prompt"),
        ("name: t\nprompt: go\ngraph: g.yaml\n", "not both"),
        ("name: t\ngraph: g.yaml\ntools: [files]\n", "belong in the graph"),
        ("name: t\nprompt: go\nevery: 1h\nat: '0 3 * * *'\n", "not every and at"),
        ("name: t\nprompt: go\nnonsense: 1\n", "nonsense"),
    ],
)
def test_a_broken_task_fails_at_load(tmp_path, body, message):
    path = write_card(tmp_path, "t", body)
    with pytest.raises(SpecError) as exc:
        load_card(path)
    assert message in str(exc.value)


def test_a_graph_card_refuses_max_turns_even_at_its_default(tmp_path):
    """The check reads the key, not the value it carries.

    `max_turns` is the one node key with a default of its own, and a person
    writing it out is likeliest to write that default. Comparing values let
    exactly that number through, and the graph then ignored it in silence.
    """
    for value in (DEFAULT_MAX_TURNS, DEFAULT_MAX_TURNS + 1):
        path = write_card(tmp_path, "t", f"name: t\ngraph: g.yaml\nmax_turns: {value}\n")
        with pytest.raises(SpecError) as exc:
            load_card(path)
        assert "max_turns belong in the graph" in str(exc.value)


def test_a_missing_folder_fails_at_load(tmp_path):
    (tmp_path / "tasks").mkdir()
    path = tmp_path / "tasks" / "t.yaml"
    path.write_text("name: t\nfolder: nowhere\nprompt: go\n", encoding="utf-8")
    with pytest.raises(SpecError, match="folder does not exist"):
        load_card(path)


# -- the daemon config -------------------------------------------------------


def _config(tmp_path: Path, extra: str = "") -> Path:
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'models/mock.yaml').as_posix()}\n"
        f"store: {(tmp_path / 'logs').as_posix()}\n"
        "tasks: tasks/\n" + extra,
        encoding="utf-8",
    )
    return config


def test_a_tasks_folder_becomes_flows(tmp_path):
    write_card(tmp_path, "one", "name: one\nprompt: go\n")
    write_card(tmp_path, "two", "name: two\nprompt: go\nenabled: false\n")
    config = load_config(_config(tmp_path))

    assert [f.name for f in config.tasks] == ["one", "two"]
    loaded = load_tasks(config, enabled_only=False)
    assert [item.graph.nodes[0].type for item in loaded] == ["agent", "agent"]
    assert [item.spec.enabled for item in loaded] == [True, False]

    assert load_tasks(config) and len(load_tasks(config)) == 1


def test_every_card_in_the_folder_becomes_a_job(tmp_path):
    write_card(tmp_path, "one", "name: one\nprompt: go\n")
    write_card(tmp_path, "two", "name: two\nprompt: go\n")

    config = load_config(_config(tmp_path))

    assert sorted(f.name for f in config.tasks) == ["one", "two"]


def test_a_missing_tasks_folder_fails_at_load(tmp_path):
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'models/mock.yaml').as_posix()}\ntasks: nope/\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="tasks folder does not exist"):
        load_config(config)


def test_a_config_that_names_no_tasks_folder_has_no_jobs(tmp_path):
    """There is no other place a job could have been written down."""
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'models/mock.yaml').as_posix()}\n",
        encoding="utf-8",
    )

    loaded = load_config(config)

    assert loaded.cards is None  # no folder named
    assert loaded.tasks == []  # and so nothing to run


# -- the journal -------------------------------------------------------------


def test_a_new_journal_gets_a_header_then_one_line_per_entry(tmp_path):
    task = load_card(write_card(tmp_path, "tidy", "name: tidy up\nprompt: go\n"))
    when = datetime(2026, 8, 22, 3, 14)

    append_journal(task.journal_path(), "did", "fixed the flaky test", title=task.name, when=when)
    append_journal(task.journal_path(), "you", "leave prose alone", title=task.name, when=when)

    text = task.journal_path().read_text(encoding="utf-8")
    assert text.startswith("# tidy up\n")
    assert "- 2026-08-22 03:14 · did     fixed the flaky test" in text
    assert "- 2026-08-22 03:14 · you     leave prose alone" in text


def test_an_entry_is_one_line_however_the_model_answers(tmp_path):
    task = load_card(write_card(tmp_path, "t", "name: t\nprompt: go\n"))
    append_journal(task.journal_path(), "did", "first line\n\nsecond   line\n")
    written = task.journal_path().read_text(encoding="utf-8")
    assert len([line for line in written.splitlines() if line.startswith("- ")]) == 1
    assert "first line second line" in written


def test_reading_an_absent_journal_says_so(tmp_path):
    task = load_card(write_card(tmp_path, "t", "name: t\nprompt: go\n"))
    assert read_journal(task.journal_path()) == "nothing yet"


def test_only_the_tail_reaches_the_prompt(tmp_path):
    task = load_card(write_card(tmp_path, "t", "name: t\nprompt: go\n"))
    for i in range(25):
        append_journal(task.journal_path(), "did", f"entry {i}", title=task.name)

    tail = read_journal(task.journal_path())
    assert "(earlier entries omitted)" in tail
    assert "entry 24" in tail and "entry 4" not in tail
    # The file itself keeps everything.
    assert "entry 0" in task.journal_path().read_text(encoding="utf-8")


def test_a_hand_written_line_is_read_like_any_other(tmp_path):
    task = load_card(write_card(tmp_path, "t", "name: t\nprompt: go\n"))
    # By hand, in an editor, before the task has ever run -- so the folder is
    # made the same way a person would make it.
    task.journal_path().parent.mkdir(parents=True, exist_ok=True)
    task.journal_path().write_text("# t\n\nstop touching the README\n", encoding="utf-8")
    assert "stop touching the README" in read_journal(task.journal_path())


def test_a_run_leaves_no_journal_among_the_definitions(tmp_path):
    """Why the journal moved at all. A card is a thing a person edits; a
    journal grows every night. Side by side, the folder of definitions went
    dirty in git on every run, whether or not a definition had changed."""
    task = load_card(write_card(tmp_path, "t", "name: t\nprompt: go\n"))
    definitions = sorted(p.name for p in (tmp_path / "tasks").glob("*.yaml"))

    append_journal(task.journal_path(), "did", "tidied one file")

    assert sorted(p.name for p in (tmp_path / "tasks").glob("*.yaml")) == definitions
    assert list((tmp_path / "tasks").glob("*.md")) == []
    assert task.journal_path() == at(tmp_path / "tasks").journal("t")
    assert "tidied one file" in task.journal_path().read_text(encoding="utf-8")


def test_the_generated_prompt_carries_the_journal(tmp_path):
    _, graph = expand(load_card(write_card(tmp_path, "t", "name: t\nprompt: go\n")))
    assert "{{ input.journal }}" in graph.nodes[0].system


def test_the_generated_prompt_puts_memory_before_the_journal(tmp_path):
    path = write_card(tmp_path, "t", "name: t\nprompt: go\n")
    write_page(tmp_path / "tasks", "Never push to main.")

    _, graph = expand(load_card(path))
    system = graph.nodes[0].system
    # The stable part of the prompt stays stable: always-true rules come
    # before recent history.
    assert system.index("{{ input.memory }}") < system.index("{{ input.journal }}")


def test_a_task_backed_flow_reads_its_journal_before_every_run(tmp_path):
    path = write_card(tmp_path, "one", "name: one\nprompt: go\n")
    config = load_config(_config(tmp_path))
    task = load_tasks(config)[0]

    assert task.read_input(config)["journal"] == "nothing yet"
    append_journal(load_card(path).journal_path(), "you", "try the tests instead")
    assert "try the tests instead" in task.read_input(config)["journal"]


async def test_a_run_writes_what_it_did_into_the_journal(tmp_path):
    from poieo.daemon import Daemon

    path = write_card(tmp_path, "one", "name: one\nprompt: go\n")
    config = load_config(_config(tmp_path))
    for task in config.tasks:
        task.trigger.max_iterations = 1

    await asyncio.wait_for(Daemon(config, store=NullStore()).serve(install_signals=False), timeout=10)

    written = load_card(path).journal_path().read_text(encoding="utf-8")
    assert written.startswith("# one\n")
    assert "· did" in written
    assert "(mock response)" in written


# -- isolation ---------------------------------------------------------------

from poieo.tools import Isolation


def _task(tmp_path, **extra):
    body = {"name": "boxed", "folder": str(tmp_path), "prompt": "do it", **extra}
    return CardSpec.model_validate(body)


def test_a_task_card_parses_an_isolation_block(tmp_path):
    task = _task(tmp_path, isolation={"image": "python:3.12-slim"})
    assert task.isolation == Isolation(image="python:3.12-slim")


def test_network_defaults_to_none(tmp_path):
    assert _task(tmp_path, isolation={"image": "x"}).isolation.network == "none"


def test_image_is_required_when_the_block_is_present(tmp_path):
    with pytest.raises(Exception):
        _task(tmp_path, isolation={"network": "bridge"})


def test_an_unknown_isolation_key_is_rejected(tmp_path):
    with pytest.raises(Exception):
        _task(tmp_path, isolation={"image": "x", "privileged": True})


def test_a_task_without_isolation_is_unchanged(tmp_path):
    assert _task(tmp_path).isolation is None


def _load(tmp_path, body):
    """expand() needs a task that came off disk, so write one."""
    (tmp_path / "work").mkdir(exist_ok=True)
    card = tmp_path / "card.yaml"
    card.write_text(f"name: boxed\nfolder: work\n{body}\nisolation:\n  image: x\n")
    return load_card(card)


def test_isolation_reaches_the_flow(tmp_path):
    """It describes the task, not the generated node, so it rides the expansion."""
    task, _graph = expand(_load(tmp_path, "prompt: do it"))
    assert task.isolation == Isolation(image="x")


def test_isolation_survives_a_task_that_names_a_graph(tmp_path):
    """Unlike prompt/role/tools, isolation is not a node key -- eject keeps it."""
    (tmp_path / "g.yaml").write_text("name: g\nentry: n\nnodes: [{id: n, type: agent, role: r, prompt: hi}]\n")
    task, graph = expand(_load(tmp_path, "graph: g.yaml"))
    assert graph is None and task.isolation == Isolation(image="x")


# -- the journal delivers, it does not just record ---------------------------
#
# A record may lose its oldest lines. A note that falls off has not aged out,
# it is lost -- so what is new is selected by position, never by count.
#
# Every test here appends *more* than the display bound after the bookmark:
# a note written last is trivially in the tail, and a test that only proves
# that proves nothing.

NEW_HEADER = "New since you last worked"
OLD_HEADER = "What you did before that"


def _worked(path, text="checked 12 links", title="check links"):
    """A run entry -- which is what a bookmark is."""
    append_journal(path, "did", text, title=title)
    return path


def _new_section(path):
    text = read_journal(path)
    if NEW_HEADER not in text:
        return ""
    return text.split(NEW_HEADER, 1)[1].split(OLD_HEADER)[0]


def test_a_note_is_not_lost_when_many_arrive(tmp_path):
    """THE test. Twenty-five notes arrive between runs and the display bound is
    twenty: the first must not be the price of the last."""
    j = _worked(tmp_path / "check-links.md")
    for i in range(25):
        append_journal(j, "task", f"[build-docs] note {i}")
    assert "note 0" in read_journal(j)


def test_a_user_note_is_not_lost_either(tmp_path):
    """The same guarantee for `poieo note` -- the bug this fixes on the way."""
    j = _worked(tmp_path / "check-links.md")
    append_journal(j, "you", "ignore external links")
    for i in range(25):
        append_journal(j, "task", f"[build-docs] note {i}")
    assert "ignore external links" in read_journal(j)


def test_a_backlog_is_shown_oldest_first_and_counts_the_rest(tmp_path):
    """Nothing is dropped. Showing the newest first would strand the oldest."""
    j = _worked(tmp_path / "check-links.md")
    for i in range(40):
        append_journal(j, "task", f"[build-docs] note {i}")
    text = read_journal(j)
    assert "note 0" in text
    assert "more waiting" in text


def test_a_failed_run_does_not_consume_a_note(tmp_path):
    """A failed run saw the note but cannot be said to have handled it."""
    j = _worked(tmp_path / "check-links.md")
    append_journal(j, "task", "[build-docs] look again")
    append_journal(j, "failed", "shell tool: command timed out")
    assert "look again" in _new_section(j)


def test_a_completed_run_does_consume_them(tmp_path):
    """Otherwise a task is told the same thing every hour, forever."""
    j = _worked(tmp_path / "check-links.md")
    append_journal(j, "task", "[build-docs] look again")
    _worked(j, "checked the 30 changed links")
    assert "look again" not in _new_section(j)


def test_nothing_new_says_so_rather_than_vanishing(tmp_path):
    """No news is information; a missing section reads as a bug."""
    j = _worked(tmp_path / "check-links.md")
    assert "nothing new" in read_journal(j).lower()


def test_a_task_that_never_ran_sees_everything_as_new(tmp_path):
    j = tmp_path / "fresh.md"
    append_journal(j, "you", "start with the README", title="fresh")
    assert "start with the README" in _new_section(j)


def test_history_is_still_bounded(tmp_path):
    """The half that is allowed to age out still ages out."""
    j = tmp_path / "check-links.md"
    for i in range(200):
        append_journal(j, "did", f"routine entry {i}", title="check links")
    text = read_journal(j)
    assert "routine entry 0" not in text
    assert "routine entry 199" in text


def test_a_hand_written_line_after_the_bookmark_is_new(tmp_path):
    """The bookmark is a line already in the file, so hand editing keeps working."""
    j = _worked(tmp_path / "check-links.md")
    with j.open("a", encoding="utf-8") as handle:
        handle.write("- whatever the user felt like typing\n")
    for i in range(25):
        append_journal(j, "task", f"[build-docs] note {i}")
    assert "whatever the user felt like typing" in read_journal(j)


def test_an_unreadable_journal_still_lets_the_run_proceed(tmp_path):
    assert read_journal(tmp_path / "does-not-exist.md") == "nothing yet"


def test_a_note_cannot_forge_a_bookmark(tmp_path):
    """The bookmark decides what counts as read, so text must not be able to
    fake one -- that would lose notes silently, which is the one failure this
    whole design exists to prevent."""
    j = _worked(tmp_path / "check-links.md")
    append_journal(j, "task", "[build-docs] · did you look at the changed links?")
    for i in range(25):
        append_journal(j, "task", f"[build-docs] note {i}")
    text = read_journal(j)
    assert "did you look at the changed links" in text
    assert "note 0" in text


# -- knowing who else is there -----------------------------------------------


def _card(tmp_path, name, tools=""):
    (tmp_path / "work").mkdir(exist_ok=True)
    path = tmp_path / f"{name}.yaml"
    path.write_text(f"name: {name}\nfolder: work\nprompt: go\n{tools}")
    return load_card(path)


def test_a_task_with_notes_is_told_who_it_can_tell(tmp_path):
    task = _card(tmp_path, "build-docs", "tools: [files, notes]\n")
    block = system_block(task, roster=["check-links", "run-tests"])
    assert "check-links" in block and "run-tests" in block


def test_a_task_without_notes_sees_no_roster(tmp_path):
    """No roster, no sentence, no hint that other tasks exist."""
    task = _card(tmp_path, "build-docs")
    block = system_block(task, roster=["check-links"])
    assert "check-links" not in block


def test_the_prompt_says_a_note_is_not_a_reply(tmp_path):
    """So the model does not sit waiting for an answer that never comes."""
    task = _card(tmp_path, "build-docs", "tools: [files, notes]\n")
    assert "next run" in system_block(task, roster=["check-links"])


def test_an_empty_roster_is_not_an_awkward_sentence(tmp_path):
    task = _card(tmp_path, "build-docs", "tools: [files, notes]\n")
    block = system_block(task, roster=[])
    assert "tell" not in block.lower()


# -- what the model said last ------------------------------------------------


def _finished(**over):
    from dataclasses import replace

    from poieo.runtime.context import RunResult

    result = RunResult(
        run_id="20260824T120000-abcd1234",
        task="tidy",
        graph="tidy",
        status="completed",
        started_at="2026-08-24T12:00:00+00:00",
        finished_at="2026-08-24T12:00:05+00:00",
        steps=2,
        path=["look", "work"],
        usage={"input_tokens": 10, "output_tokens": 5},
        outputs={"look": "poked around", "work": "fixed the parser\nand tidied up\n"},
        state={},
    )
    return replace(result, **over)


def test_the_journal_the_record_and_the_commit_read_one_line():
    """Three readers, one reading. The journal entry, the run record's summary
    and the change's commit subject all come from the last node that said
    anything -- so they can never tell a reader three stories about one run."""
    from poieo.card import closing_line
    from poieo.daemon.service import _change_message

    result = _finished()
    assert closing_line(result) == "fixed the parser\nand tidied up\n"
    # The commit subject is the same sentence, shaped for `git log --oneline`.
    assert _change_message(result, "tidy") == "fixed the parser"


def test_a_run_that_said_nothing_falls_back_where_each_reader_needs_to():
    from poieo.card import closing_line
    from poieo.daemon.service import _change_message

    silent = _finished(path=["work"], outputs={"work": "   "})
    assert closing_line(silent) == "(said nothing)"
    # A commit cannot say "(said nothing)" usefully; it names the run instead.
    assert _change_message(silent, "tidy") == "poieo tidy 20260824T120000-abcd1234"


def test_a_long_line_is_clipped_for_the_commit_but_not_for_the_record():
    from poieo.card import closing_line
    from poieo.daemon.service import _change_message

    said = "went through every file and " + "x" * 200
    result = _finished(path=["work"], outputs={"work": said})
    assert closing_line(result) == said  # the record keeps all of it
    assert len(_change_message(result, "tidy")) == 72


def test_a_card_that_only_names_a_graph_and_a_trigger_is_a_card():
    """`graph:` and `trigger:` are the two most card-shaped words there are --
    a graph has neither -- and neither was evidence.

    A card with no `folder:` and no `then:` fell through to being read as a
    graph, and the error a person got said `'graph' is not a setting here`
    about the very key that makes it a card.
    """
    assert is_card_document({"name": "nightly", "graph": "g.yaml", "trigger": {"type": "manual"}})
    assert is_card_document({"name": "nightly", "graph": "g.yaml"})


def test_a_graph_is_still_a_graph():
    """`nodes:` outranks everything, and a file with neither is neither."""
    assert not is_card_document({"name": "g", "entry": "a", "nodes": [{"id": "a"}]})
    assert not is_card_document({"name": "proj", "store": "runs", "binding": "b.yaml"})


# -- the shipped chain --------------------------------------------------------


def test_the_example_project_ships_a_chain_of_handoffs():
    """Nothing demonstrated `then:` until this, which is why nobody could see it.

    The board's central rule is that **an arrow crossing a border is a new
    run** -- a new private copy, and one more thing to accept or discard. A
    reader who opens the sample project and finds no arrow anywhere has no way
    to meet that rule, and the pair of tasks that were already there talk
    through notes instead, which is a different mechanism on purpose.
    """
    config = load_config(EXAMPLES / "poieo.yaml")
    by_name = {task.name: task for task in config.tasks}

    hands = {name: [(branch.to, branch.label) for branch in task.then] for name, task in by_name.items() if task.then}
    assert hands["night-watch"] == [("mend", "red")]
    assert hands["mend"] == [("tell-me", "green again")]
    # The end of a chain says nothing, rather than saying "nowhere": falling
    # off the end is what almost every task does.
    assert not by_name["tell-me"].then

    # Every target is a task and nothing points at itself. It is also a chain
    # rather than a ring: a catch-all last branch back to the first task reads
    # like a retry, loads with a warning, and then two tasks wake each other
    # for as long as the chain depth allows -- which is not what an example
    # somebody arms should do on its first night.
    check_handoffs(config)


def test_the_chain_only_wakes_on_a_handoff():
    """A task with no schedule is not a broken task. `mend` has nothing to say
    about a suite nobody reported broken, so it waits to be woken."""
    config = load_config(EXAMPLES / "poieo.yaml")
    by_name = {task.name: task for task in config.tasks}

    assert by_name["mend"].trigger.type == "manual"
    assert by_name["tell-me"].trigger.type == "manual"
    assert by_name["night-watch"].trigger.type == "interval"


def test_the_chain_looks_but_does_not_touch():
    """Three tasks that only answer. A prompt-shaped task is given the files
    and shell toolsets unless it says otherwise, and an example that anybody
    may arm should not be handed more than it needs."""
    loaded = {item.spec.name: item for item in load_tasks(load_config(EXAMPLES / "poieo.yaml"))}

    for name in ("night-watch", "mend", "tell-me"):
        assert loaded[name].graph.nodes[0].tools == [], name


def test_a_card_that_asks_for_no_tools_is_given_none(tmp_path):
    """`None` is "the card did not say", and a card-made task is meant to have
    hands. `[]` is the card saying none -- and `or` read the two as one, so a
    task written to be harmless was handed the files and shell toolsets anyway.

    Of all the places a key can read as configured and do nothing, this is the
    one that costs more than a puzzled reader.
    """
    quiet = write_card(tmp_path, "quiet", "name: quiet\nprompt: look\ntools: []\n")
    ordinary = write_card(tmp_path, "ordinary", "name: ordinary\nprompt: work\n")

    assert expand(load_card(quiet))[1].nodes[0].tools == []
    assert expand(load_card(ordinary))[1].nodes[0].tools == ["files", "shell"]
