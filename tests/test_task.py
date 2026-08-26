"""A task is one file that expands into a flow plus a one-node graph.

The expansion tests compare against the hand-written equivalent on purpose:
that equality is the whole safety argument for the sugar.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from poieo.daemon.config import FlowSpec, load_config, load_flows
from poieo.errors import SpecError
from poieo.graph import GraphSpec
from poieo.store import NullStore
from poieo.task import (
    TaskSpec,
    append_journal,
    expand,
    load_task,
    load_tasks,
    read_journal,
    system_block,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def write_task(root: Path, stem: str, body: str, folder: Path | None = None) -> Path:
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
    path = write_task(
        tmp_path,
        "keep-improving",
        "name: keep improving poieo\nprompt: |\n  Fix one thing.\n",
    )
    flow, graph = expand(load_task(path))

    assert flow == FlowSpec(
        name="keep-improving",
        graph=str(path),
        trigger={"type": "interval", "every": "1h"},
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
                "workdir": str(tmp_path / "project"),
                "tools": ["files", "shell"],
                "max_turns": 40,
                "system": graph.nodes[0].system,
                "prompt": "Fix one thing.\n",
                "output": {"as": "summary"},
            }
        ],
    )


def test_the_generated_prompt_asks_for_a_one_line_summary(tmp_path):
    path = write_task(tmp_path, "t", "name: tidy up\nprompt: go\n")
    _, graph = expand(load_task(path))
    assert "one line" in graph.nodes[0].system
    assert "tidy up" in graph.nodes[0].system


def test_optional_keys_land_on_the_node(tmp_path):
    path = write_task(
        tmp_path,
        "t",
        "name: t\nprompt: go\nrole: worker\ntools: [files]\nmax_turns: 5\n",
    )
    _, graph = expand(load_task(path))
    node = graph.nodes[0]
    assert (node.role, node.tools, node.max_turns) == ("worker", ["files"], 5)


def test_a_card_that_names_no_tools_gets_the_one_default_toolset(tmp_path):
    """The card's default and the agent node's default are one constant.

    They used to be two lists spelled the same in two modules, which is a
    thing that stays true right up until it doesn't.
    """
    from poieo.tools import DEFAULT_TOOLSETS

    _, graph = expand(load_task(write_task(tmp_path, "t", "name: t\nprompt: go\n")))
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
    flow, _ = expand(load_task(write_task(tmp_path, "t", body)))
    assert flow.trigger.type == expected["type"]
    if "every" in expected:
        assert flow.trigger.every == expected["every"]


def test_identity_comes_from_the_filename_not_the_title(tmp_path):
    path = write_task(tmp_path, "keep-improving", "name: a title I will rewrite\nprompt: go\n")
    flow, graph = expand(load_task(path))
    assert flow.name == "keep-improving"
    assert graph.name == "keep-improving"


def test_an_ejected_task_names_its_graph_instead_of_generating_one(tmp_path):
    graphs = tmp_path / "graphs"
    graphs.mkdir()
    (graphs / "t.yaml").write_text(
        "name: t\nentry: a\nnodes:\n  - {id: a, type: llm, prompt: hi}\n", encoding="utf-8"
    )
    path = write_task(tmp_path, "t", "name: t\ngraph: ../graphs/t.yaml\n")
    flow, graph = expand(load_task(path))
    assert graph is None
    assert Path(flow.graph) == (graphs / "t.yaml").resolve()


# -- cards and graphs share a folder -----------------------------------------
#
# A card is a graph's short form, so the two are one kind of thing -- what a
# person writes -- and live together. Which is which is a question the
# document answers: a card has a folder, a graph has nodes.


def write_graph(root: Path, stem: str) -> Path:
    tasks = root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    path = tasks / f"{stem}.graph.yaml"
    path.write_text(
        "name: g\nentry: a\nnodes:\n  - {id: a, type: llm, prompt: hi}\n", encoding="utf-8"
    )
    return path


def test_a_graph_beside_a_card_is_not_read_as_a_card(tmp_path):
    write_task(tmp_path, "tidy", "name: tidy\nprompt: go\n")
    write_graph(tmp_path, "tidy")
    assert [task.slug for task in load_tasks(tmp_path / "tasks")] == ["tidy"]


def test_a_file_that_is_neither_says_so_instead_of_vanishing(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "confused.yaml").write_text("name: neither\nversion: 1\n", encoding="utf-8")
    with pytest.raises(SpecError) as caught:
        load_tasks(tasks)
    # Both shapes are named, because "this is wrong" without "here is what
    # right looks like" is where a person goes to read the source.
    assert "folder:" in str(caught.value) and "nodes:" in str(caught.value)


def test_a_file_answering_to_both_shapes_fails_rather_than_disappearing(tmp_path):
    """A card that grew a `nodes:` key answers to no rule. Reading it as a
    graph would drop a task from the roster without a word."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "both.yaml").write_text(
        "name: both\nfolder: .\nnodes:\n  - {id: a, type: llm}\n", encoding="utf-8"
    )
    with pytest.raises(SpecError):
        load_tasks(tasks)


def test_a_card_whose_yaml_is_broken_still_fails_the_load(tmp_path):
    """The trap this folder invites: sorting cards from graphs by *trying* to
    parse would turn a typo into a silently absent task -- a card that stops
    running at 3am with nothing said. It fails here instead."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "broken.yaml").write_text("name: broken\n  folder: .\n", encoding="utf-8")
    with pytest.raises(SpecError):
        load_tasks(tasks)


def test_a_card_with_an_unknown_key_still_fails_the_load(tmp_path):
    write_task(tmp_path, "tidy", "name: tidy\nprompt: go\nbogus: 1\n")
    with pytest.raises(SpecError):
        load_tasks(tmp_path / "tasks")


def test_paths_resolve_against_the_task_file(tmp_path):
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "here").mkdir()
    path = tmp_path / "tasks" / "t.yaml"
    path.write_text("name: t\nfolder: here\nprompt: go\n", encoding="utf-8")
    _, graph = expand(load_task(path))
    assert graph.nodes[0].workdir == str(tmp_path / "tasks" / "here")


# -- refusals ----------------------------------------------------------------


@pytest.mark.parametrize(
    "body, message",
    [
        ("name: t\n", "needs a prompt"),
        ("name: t\nprompt: go\ngraph: g.yaml\n", "not both"),
        ("name: t\ngraph: g.yaml\ntools: [files]\n", "belong in the graph"),
        ("name: t\nprompt: go\nevery: 1h\nat: '0 3 * * *'\n", "not both"),
        ("name: t\nprompt: go\nnonsense: 1\n", "nonsense"),
    ],
)
def test_a_broken_task_fails_at_load(tmp_path, body, message):
    path = write_task(tmp_path, "t", body)
    with pytest.raises(SpecError) as exc:
        load_task(path)
    assert message in str(exc.value)


def test_a_missing_folder_fails_at_load(tmp_path):
    (tmp_path / "tasks").mkdir()
    path = tmp_path / "tasks" / "t.yaml"
    path.write_text("name: t\nfolder: nowhere\nprompt: go\n", encoding="utf-8")
    with pytest.raises(SpecError, match="folder does not exist"):
        load_task(path)


# -- the daemon config -------------------------------------------------------


def _config(tmp_path: Path, extra: str = "") -> Path:
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\n"
        f"store: {(tmp_path / 'logs').as_posix()}\n"
        "tasks: tasks/\n" + extra,
        encoding="utf-8",
    )
    return config


def test_a_tasks_folder_becomes_flows(tmp_path):
    write_task(tmp_path, "one", "name: one\nprompt: go\n")
    write_task(tmp_path, "two", "name: two\nprompt: go\nenabled: false\n")
    config = load_config(_config(tmp_path))

    assert [f.name for f in config.flows] == ["one", "two"]
    loaded = load_flows(config, enabled_only=False)
    assert [item.graph.nodes[0].type for item in loaded] == ["agent", "agent"]
    assert [item.spec.enabled for item in loaded] == [True, False]

    assert load_flows(config) and len(load_flows(config)) == 1


def test_tasks_and_explicit_flows_live_side_by_side(tmp_path):
    write_task(tmp_path, "one", "name: one\nprompt: go\n")
    config = load_config(
        _config(
            tmp_path,
            "flows:\n"
            "  - name: legacy\n"
            f"    graph: {(EXAMPLES / 'graphs/support-triage.yaml').as_posix()}\n",
        )
    )
    assert sorted(f.name for f in config.flows) == ["legacy", "one"]


def test_a_task_colliding_with_a_flow_fails_at_load(tmp_path):
    write_task(tmp_path, "one", "name: one\nprompt: go\n")
    config_path = _config(
        tmp_path,
        "flows:\n"
        "  - name: one\n"
        f"    graph: {(EXAMPLES / 'graphs/support-triage.yaml').as_posix()}\n",
    )
    with pytest.raises(SpecError, match="already a flow"):
        load_config(config_path)


def test_a_missing_tasks_folder_fails_at_load(tmp_path):
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\ntasks: nope/\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="tasks folder does not exist"):
        load_config(config)


def test_a_config_without_tasks_is_untouched(tmp_path):
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\n"
        "flows:\n"
        "  - name: legacy\n"
        f"    graph: {(EXAMPLES / 'graphs/support-triage.yaml').as_posix()}\n",
        encoding="utf-8",
    )
    loaded = load_config(config)
    assert loaded.tasks is None
    assert [f.name for f in loaded.flows] == ["legacy"]


# -- the journal -------------------------------------------------------------


def test_a_new_journal_gets_a_header_then_one_line_per_entry(tmp_path):
    task = load_task(write_task(tmp_path, "tidy", "name: tidy up\nprompt: go\n"))
    when = datetime(2026, 8, 22, 3, 14)

    append_journal(task.journal_path(), "did", "fixed the flaky test", title=task.name, when=when)
    append_journal(task.journal_path(), "you", "leave prose alone", title=task.name, when=when)

    text = task.journal_path().read_text(encoding="utf-8")
    assert text.startswith("# tidy up\n")
    assert "- 2026-08-22 03:14 · did     fixed the flaky test" in text
    assert "- 2026-08-22 03:14 · you     leave prose alone" in text


def test_an_entry_is_one_line_however_the_model_answers(tmp_path):
    task = load_task(write_task(tmp_path, "t", "name: t\nprompt: go\n"))
    append_journal(task.journal_path(), "did", "first line\n\nsecond   line\n")
    written = task.journal_path().read_text(encoding="utf-8")
    assert len([line for line in written.splitlines() if line.startswith("- ")]) == 1
    assert "first line second line" in written


def test_reading_an_absent_journal_says_so(tmp_path):
    task = load_task(write_task(tmp_path, "t", "name: t\nprompt: go\n"))
    assert read_journal(task.journal_path()) == "nothing yet"


def test_only_the_tail_reaches_the_prompt(tmp_path):
    task = load_task(write_task(tmp_path, "t", "name: t\nprompt: go\n"))
    for i in range(25):
        append_journal(task.journal_path(), "did", f"entry {i}", title=task.name)

    tail = read_journal(task.journal_path())
    assert "(earlier entries omitted)" in tail
    assert "entry 24" in tail and "entry 4" not in tail
    # The file itself keeps everything.
    assert "entry 0" in task.journal_path().read_text(encoding="utf-8")


def test_a_hand_written_line_is_read_like_any_other(tmp_path):
    task = load_task(write_task(tmp_path, "t", "name: t\nprompt: go\n"))
    task.journal_path().write_text("# t\n\nstop touching the README\n", encoding="utf-8")
    assert "stop touching the README" in read_journal(task.journal_path())


def test_the_generated_prompt_carries_the_journal(tmp_path):
    _, graph = expand(load_task(write_task(tmp_path, "t", "name: t\nprompt: go\n")))
    assert "{{ input.journal }}" in graph.nodes[0].system


def test_the_generated_prompt_puts_memory_before_the_journal(tmp_path):
    path = write_task(tmp_path, "t", "name: t\nprompt: go\n")
    memory = tmp_path / "tasks" / "memory"
    memory.mkdir()
    (memory / "constitution.md").write_text("Never push to main.", encoding="utf-8")

    _, graph = expand(load_task(path))
    system = graph.nodes[0].system
    # The stable part of the prompt stays stable: always-true rules come
    # before recent history.
    assert system.index("{{ input.memory }}") < system.index("{{ input.journal }}")


def test_a_task_backed_flow_reads_its_journal_before_every_run(tmp_path):
    path = write_task(tmp_path, "one", "name: one\nprompt: go\n")
    config = load_config(_config(tmp_path))
    flow = load_flows(config)[0]

    assert flow.read_input(config)["journal"] == "nothing yet"
    append_journal(load_task(path).journal_path(), "you", "try the tests instead")
    assert "try the tests instead" in flow.read_input(config)["journal"]


async def test_a_run_writes_what_it_did_into_the_journal(tmp_path):
    from poieo.daemon import Daemon

    path = write_task(tmp_path, "one", "name: one\nprompt: go\n")
    config = load_config(_config(tmp_path))
    for flow in config.flows:
        flow.trigger.max_iterations = 1

    await asyncio.wait_for(
        Daemon(config, store=NullStore()).serve(install_signals=False), timeout=10
    )

    written = load_task(path).journal_path().read_text(encoding="utf-8")
    assert written.startswith("# one\n")
    assert "· did" in written
    assert "(mock response)" in written


# -- isolation ---------------------------------------------------------------

from poieo.tools import Isolation


def _task(tmp_path, **extra):
    body = {"name": "boxed", "folder": str(tmp_path), "prompt": "do it", **extra}
    return TaskSpec.model_validate(body)


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
    return load_task(card)


def test_isolation_reaches_the_flow(tmp_path):
    """It describes the task, not the generated node, so it rides the expansion."""
    flow, _graph = expand(_load(tmp_path, "prompt: do it"))
    assert flow.isolation == Isolation(image="x")


def test_isolation_survives_a_task_that_names_a_graph(tmp_path):
    """Unlike prompt/role/tools, isolation is not a node key -- eject keeps it."""
    (tmp_path / "g.yaml").write_text(
        "name: g\nentry: n\nnodes: [{id: n, type: llm, role: r, prompt: hi}]\n"
    )
    flow, graph = expand(_load(tmp_path, "graph: g.yaml"))
    assert graph is None and flow.isolation == Isolation(image="x")

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
    return load_task(path)


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
        flow="tidy",
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
    from poieo.daemon.service import _change_message
    from poieo.task import closing_line

    result = _finished()
    assert closing_line(result) == "fixed the parser\nand tidied up\n"
    # The commit subject is the same sentence, shaped for `git log --oneline`.
    assert _change_message(result, "tidy") == "fixed the parser"


def test_a_run_that_said_nothing_falls_back_where_each_reader_needs_to():
    from poieo.daemon.service import _change_message
    from poieo.task import closing_line

    silent = _finished(path=["work"], outputs={"work": "   "})
    assert closing_line(silent) == "(said nothing)"
    # A commit cannot say "(said nothing)" usefully; it names the run instead.
    assert _change_message(silent, "tidy") == "poieo tidy 20260824T120000-abcd1234"


def test_a_long_line_is_clipped_for_the_commit_but_not_for_the_record():
    from poieo.daemon.service import _change_message
    from poieo.task import closing_line

    said = "went through every file and " + "x" * 200
    result = _finished(path=["work"], outputs={"work": said})
    assert closing_line(result) == said          # the record keeps all of it
    assert len(_change_message(result, "tidy")) == 72
