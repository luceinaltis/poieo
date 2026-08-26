"""Every task run leaves one full record behind.

The journal keeps one line per run; the record keeps the whole result,
unclipped, so anything the project later claims to have learned can be traced
back to the run that taught it. The harness writes it -- there is no tool, so
nothing depends on a model remembering to remember.
"""

import json
from dataclasses import replace

import pytest

from conftest import EXAMPLES, at
from poieo.binding import BindingSpec
from poieo.daemon.config import load_config, load_flows
from poieo.errors import SpecError
from poieo.graph import GraphSpec, NodeSpec
from poieo.providers import ProviderPool
from poieo.runtime.context import RunResult
from poieo.runtime.executor import execute
from poieo.store import RunStore
from poieo.memory import check_memory, load_facts
from poieo.task import (
    JOURNAL_WIDTH,
    load_task,
    record_run,
    system_block,
    task_payload,
)

from test_task import write_task


def _task(tmp_path):
    return load_task(write_task(tmp_path, "tidy", "name: tidy the project\nprompt: go\n"))


def _result(**over):
    result = RunResult(
        run_id="20260824T120000-abcd1234",
        flow="tidy",
        graph="tidy",
        status="completed",
        started_at="2026-08-24T12:00:00+00:00",
        finished_at="2026-08-24T12:00:05+00:00",
        steps=1,
        path=["work"],
        usage={"input_tokens": 10, "output_tokens": 5},
        outputs={"work": "tidied the docs folder"},
        state={},
    )
    return replace(result, **over)


def _episode(task, result):
    return task.dir / ".poieo" / "episodes" / f"{result.run_id}.json"


def test_a_completed_run_leaves_an_episode(tmp_path):
    task, result = _task(tmp_path), _result()
    record_run(task, result)

    data = json.loads(_episode(task, result).read_text(encoding="utf-8"))
    assert data["run_id"] == result.run_id
    assert data["task"] == "tidy"
    assert data["status"] == "completed"
    assert data["summary"] == "tidied the docs folder"
    assert data["usage"] == result.usage
    assert data["folder"] == str(task.folder_path())


def test_a_failed_run_leaves_an_episode_too(tmp_path):
    task = _task(tmp_path)
    result = _result(status="failed", error="the tests would not pass", outputs={})
    record_run(task, result)

    data = json.loads(_episode(task, result).read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["error"] == "the tests would not pass"


def test_the_episode_summary_is_not_clipped(tmp_path):
    task = _task(tmp_path)
    said = "went through every file and " + "x" * (2 * JOURNAL_WIDTH)
    result = _result(outputs={"work": said})
    record_run(task, result)

    data = json.loads(_episode(task, result).read_text(encoding="utf-8"))
    assert data["summary"] == said
    # The journal keeps its one bounded line; the record is the unclipped copy.
    journal = task.journal_path().read_text(encoding="utf-8")
    assert said not in journal


def test_the_episode_joins_the_run_log_by_run_id(tmp_path):
    task, result = _task(tmp_path), _result()
    record_run(task, result)

    path = _episode(task, result)
    assert path.stem == result.run_id
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == result.run_id


async def test_a_graph_without_a_task_leaves_no_episode(tmp_path):
    graph = GraphSpec(
        name="adhoc",
        entry="step",
        nodes=[NodeSpec(id="step", type="llm", prompt="say hi")],
    )
    binding = BindingSpec.model_validate(
        {
            "name": "test",
            "providers": {"fake": {"type": "mock", "options": {"fallback": "hi"}}},
            "default": {"provider": "fake", "model": "mock-model"},
        }
    )
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, RunStore(tmp_path / ".poieo"))

    assert result.status == "completed"
    assert not (tmp_path / ".poieo" / "episodes").exists()


def test_an_existing_episode_is_never_rewritten(tmp_path):
    task, result = _task(tmp_path), _result()
    record_run(task, result)

    _episode(task, result).write_text('{"kept": true}', encoding="utf-8")
    record_run(task, result)
    assert json.loads(_episode(task, result).read_text(encoding="utf-8")) == {"kept": True}


def test_an_unwritable_episode_is_logged_and_the_result_stands(tmp_path, caplog):
    task, result = _task(tmp_path), _result()
    # A file where the episodes folder should be: every write must fail.
    (task.dir / ".poieo").mkdir()
    (task.dir / ".poieo" / "episodes").write_text("in the way", encoding="utf-8")

    with caplog.at_level("WARNING", logger="poieo.memory"):
        record_run(task, result)

    assert any("episode" in message for message in caplog.messages)
    # The journal line still landed: the run's memory does not hinge on the record.
    assert "tidied the docs folder" in task.journal_path().read_text(encoding="utf-8")


# -- the page every run reads ------------------------------------------------
#
# The zero-configuration invariant is the point: a project that never made a
# memory must see no trace of the feature, byte for byte. Everything else is
# the two injection paths agreeing with each other.


TODAY_WITHOUT_MEMORY = (
    "You are working on {name}, in {folder}.\n\n"
    "What you have already done, and what the user has told you:\n"
    "{{{{ input.journal }}}}\n\n"
    "Finish by saying in one line what you did. If there was nothing worth\n"
    "doing, say that in one line instead."
)


def _remember(tmp_path, text="Never push to main."):
    memory = at(tmp_path / "tasks")
    memory.longterm().mkdir(parents=True, exist_ok=True)
    memory.constitution().write_text(text, encoding="utf-8")
    return memory


def _daemon_flow(tmp_path):
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\n"
        f"store: {(tmp_path / 'logs').as_posix()}\n"
        "tasks: tasks/\n",
        encoding="utf-8",
    )
    loaded_config = load_config(config)
    return load_flows(loaded_config)[0], loaded_config


def test_no_memory_folder_means_prompts_identical_to_today(tmp_path):
    task = _task(tmp_path)
    assert system_block(task) == TODAY_WITHOUT_MEMORY.format(
        name=task.name, folder=task.folder_path()
    )
    assert "memory" not in task_payload(task)

    flow, config = _daemon_flow(tmp_path)
    assert "memory" not in flow.read_input(config)
    assert "{{ input.memory }}" not in flow.graph.nodes[0].system


def test_the_constitution_reaches_the_prompt_on_the_daemon_path(tmp_path):
    _task(tmp_path)
    _remember(tmp_path)
    flow, config = _daemon_flow(tmp_path)

    assert "{{ input.memory }}" in flow.graph.nodes[0].system
    block = flow.read_input(config)["memory"]
    assert block.startswith("What this project always requires:")
    assert "Never push to main." in block


def test_the_constitution_reaches_the_prompt_on_the_cli_path(tmp_path):
    task = _task(tmp_path)
    _remember(tmp_path)

    assert "{{ input.memory }}" in system_block(task)
    block = task_payload(task)["memory"]
    assert "Never push to main." in block


def test_both_runners_hand_a_card_the_same_input(tmp_path):
    """`poieo run` on a card and the daemon on that card must agree.

    The two used to spell the rule out separately, once in cli.py and once in
    daemon/config.py, so a third input key could reach one runner and not the
    other -- and the daemon's half only shows up at 3am.
    """
    task = _task(tmp_path)
    _remember(tmp_path)
    flow, config = _daemon_flow(tmp_path)

    assert flow.read_input(config) == task_payload(task)


def test_an_edit_takes_effect_next_run_without_reload(tmp_path):
    _task(tmp_path)
    memory = _remember(tmp_path)
    flow, config = _daemon_flow(tmp_path)
    assert "Never push to main." in flow.read_input(config)["memory"]

    memory.constitution().write_text("Ship one change at a time.", encoding="utf-8")
    assert "Ship one change at a time." in flow.read_input(config)["memory"]


def test_a_malformed_fact_fails_at_load_naming_the_file(tmp_path):
    _task(tmp_path)
    facts = _remember(tmp_path).facts()
    facts.mkdir()
    (facts / "batch-sizes.md").write_text(
        "---\nscope: [global]\nseverity: high\n---\nThe API caps batches at 50.\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="batch-sizes.md"):
        _daemon_flow(tmp_path)


def test_an_oversized_page_warns_and_still_loads_whole(tmp_path, caplog):
    task = _task(tmp_path)
    long_page = "Never push to main.\n" * 1500
    _remember(tmp_path, long_page)

    with caplog.at_level("WARNING", logger="poieo.memory"):
        block = task_payload(task)["memory"]

    assert long_page.strip() in block
    assert any("trim" in message for message in caplog.messages)


def test_editor_notes_in_the_page_never_reach_the_prompt(tmp_path):
    task = _task(tmp_path)
    _remember(
        tmp_path,
        "<!-- ask the four questions before adding a line -->\nNever push to main.",
    )
    block = task_payload(task)["memory"]
    assert "Never push to main." in block
    assert "four questions" not in block


def test_an_empty_memory_folder_behaves_as_absent(tmp_path):
    task = _task(tmp_path)
    at(tmp_path / "tasks").longterm().mkdir(parents=True)

    assert system_block(task) == TODAY_WITHOUT_MEMORY.format(
        name=task.name, folder=task.folder_path()
    )
    assert "memory" not in task_payload(task)


def test_a_journal_alone_does_not_turn_the_long_memory_on(tmp_path):
    """The one hazard in moving the journals under `memory/`: the folder now
    arrives by itself, the first time any task runs. So the opt-in cannot be
    `memory/` -- a signal that switches itself on is not consent. It is
    `memory/longterm/`, which only a person makes.
    """
    from poieo.memory import keeps_memory

    task = _task(tmp_path)
    project = tmp_path / "tasks"
    at(project).shortterm().mkdir(parents=True)
    at(project).journal(task.slug).write_text("- did: something\n", encoding="utf-8")

    assert keeps_memory(project) is False
    assert "memory" not in task_payload(task)


def test_listing_a_project_writes_nothing(tmp_path):
    # A generated prompt is built by `tasks`, `show`, and the daemon's load;
    # none of them is a run, so none of them may leave machinery behind.
    task = _task(tmp_path)
    _remember(tmp_path)
    _learn(tmp_path, "tidy-order", "Tidy the project one file at a time.")

    system_block(task)
    assert not (tmp_path / "tasks" / ".poieo").exists()


# -- the record says what the run had in mind --------------------------------


def test_an_episode_records_what_the_run_was_shown(tmp_path):
    task, result = _task(tmp_path), _result()
    _remember(tmp_path)
    _learn(tmp_path, "tidy-order", "Tidy the project one file at a time.")
    _learn(tmp_path, "elsewhere", "The exporter flushes nightly.", )

    record_run(task, result)
    data = json.loads(_episode(task, result).read_text(encoding="utf-8"))
    assert "tidy-order" in data["shown"]
    assert "elsewhere" not in data["shown"]


def test_a_memoryless_projects_episode_records_nothing_new(tmp_path):
    task, result = _task(tmp_path), _result()
    record_run(task, result)

    data = json.loads(_episode(task, result).read_text(encoding="utf-8"))
    assert "shown" not in data


def test_a_shown_recording_failure_never_fails_the_run(tmp_path, monkeypatch):
    import poieo.memory.episodes as episodes_module

    task, result = _task(tmp_path), _result()
    _remember(tmp_path)

    def blow_up(*args, **kwargs):
        raise RuntimeError("selection went sideways")

    # Patched where the record is written, which is where it is looked up.
    monkeypatch.setattr(episodes_module, "recall", blow_up)
    record_run(task, result)  # must not raise

    data = json.loads(_episode(task, result).read_text(encoding="utf-8"))
    assert data["run_id"] == result.run_id
    assert "tidied the docs folder" in task.journal_path().read_text(encoding="utf-8")


# -- entries naming each other -----------------------------------------------
#
# A connection is a judgment and lives in the files: prose mentions never
# fail anything, typed claims validate at load like every other spec poieo
# reads.


def _learn(tmp_path, slug, text):
    facts = at(tmp_path / "tasks").facts()
    facts.mkdir(parents=True, exist_ok=True)
    (facts / f"{slug}.md").write_text(text, encoding="utf-8")
    return tmp_path / "tasks"


def test_a_mention_in_the_body_is_read(tmp_path):
    project = _learn(tmp_path, "retry", "Retry once, after the window. See [[rate-limits]].")

    (fact,) = load_facts(project)
    assert fact.mentions == ["rate-limits"]


def test_typed_links_in_frontmatter_are_read(tmp_path):
    _learn(tmp_path, "batch-cap", "Batches cap at 50.")
    _learn(tmp_path, "old-advice", "Retry forever.")
    project = _learn(
        tmp_path,
        "retry",
        "---\nlinks:\n  depends_on: [batch-cap]\n  contradicts: [old-advice]\n---\nRetry once.",
    )

    fact = next(f for f in load_facts(project) if f.slug == "retry")
    assert fact.matter.links.depends_on == ["batch-cap"]
    assert fact.matter.links.contradicts == ["old-advice"]


def test_an_unknown_link_kind_fails_at_load_naming_the_file(tmp_path):
    project = _learn(
        tmp_path, "retry", "---\nlinks:\n  caused_by: [something]\n---\nRetry once."
    )
    with pytest.raises(SpecError, match="retry.md"):
        load_facts(project)


def test_a_typed_link_to_nothing_fails_at_load_naming_both(tmp_path):
    project = _learn(
        tmp_path, "retry", "---\nlinks:\n  depends_on: [ghost]\n---\nRetry once."
    )
    with pytest.raises(SpecError, match="ghost") as caught:
        check_memory(project)
    assert "retry.md" in str(caught.value)


def test_a_dangling_superseded_by_now_fails_at_load(tmp_path):
    project = _learn(tmp_path, "retry", "---\nsuperseded_by: ghost\n---\nRetry once.")
    with pytest.raises(SpecError, match="ghost"):
        check_memory(project)


def test_a_body_mention_of_nothing_is_legal(tmp_path):
    project = _learn(tmp_path, "retry", "Retry once. [[worth-writing-someday]]")

    check_memory(project)
    (fact,) = load_facts(project)
    assert fact.mentions == ["worth-writing-someday"]


def test_an_entry_saved_with_a_bom_keeps_its_frontmatter(tmp_path):
    # Notepad and PowerShell's utf8 both write a BOM; the frontmatter must
    # not silently become body text because of an invisible first character.
    _learn(tmp_path, "other", "Something to point at.")
    project = _learn(
        tmp_path,
        "retry",
        "﻿---\nlinks:\n  depends_on: [other]\n---\nRetry once.",
    )
    fact = next(f for f in load_facts(project) if f.slug == "retry")
    assert fact.matter.links.depends_on == ["other"]
    assert "---" not in fact.body


def test_sealed_naming_a_missing_anchor_fails_at_load(tmp_path):
    project = _learn(
        tmp_path,
        "feeds-note",
        '---\nanchors: []\nsealed: {"notebook/feeds.md": "'
        + "0" * 64
        + '"}\n---\nFeeds land in one file.',
    )
    with pytest.raises(SpecError, match="feeds-note.md"):
        check_memory(project)


def test_a_restored_entry_naming_an_attic_entry_still_loads(tmp_path):
    # Restoring from the attic is "move the file back" -- so a typed claim
    # naming an entry that is resting in the attic must not fail the load.
    _learn(tmp_path, "old-cap", "---\nsuperseded_by: new-cap\n---\nCaps sat at 10 once.")
    attic = at(tmp_path / "tasks").attic()
    attic.mkdir()
    (attic / "new-cap.md").write_text("Caps sit at 50 now.", encoding="utf-8")

    check_memory(tmp_path / "tasks")  # must not raise
    # A genuine typo -- a name that exists nowhere -- still fails.
    project = _learn(
        tmp_path, "typo", "---\nlinks:\n  depends_on: [ghost]\n---\nLeans on air."
    )
    with pytest.raises(SpecError, match="ghost"):
        check_memory(project)


def test_leaning_on_a_set_aside_entry_is_legal_at_load(tmp_path):
    _learn(tmp_path, "new-cap", "Batches cap at 500 now.")
    _learn(tmp_path, "old-cap", "---\nsuperseded_by: new-cap\n---\nBatches cap at 50.")
    project = _learn(
        tmp_path, "retry", "---\nlinks:\n  depends_on: [old-cap]\n---\nRetry once."
    )
    check_memory(project)  # legal; the report will flag it, nothing breaks


# -- the shape of the package ------------------------------------------------


def test_the_package_does_not_shadow_its_own_submodules():
    """A `from .recall import recall` in __init__ makes `poieo.memory.recall`
    the *function*, so `import poieo.memory.recall as m` hands back something
    with no module attributes on it. That is not theoretical -- it is how the
    first draft of this split broke three tests that patch a module global."""
    import types

    import poieo.memory as memory

    for name in ("facts", "index", "recall", "episodes", "upkeep"):
        __import__(f"poieo.memory.{name}")
        assert isinstance(getattr(memory, name), types.ModuleType), (
            f"poieo.memory.{name} is shadowed by a re-export of the same name"
        )


def test_the_learning_pass_reaches_for_nothing_private():
    """learn.py used to import four underscore names from memory. Each one was
    a signal that the package's public surface was drawn in the wrong place,
    and the split is what moved it -- so nothing should need them again."""
    import pathlib

    import poieo.learn

    source = pathlib.Path(poieo.learn.__file__).read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if "memory import" in line and " _" in line
    ]
    assert offenders == []
