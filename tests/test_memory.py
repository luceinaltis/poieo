"""Every task run leaves one full record behind.

The journal keeps one line per run; the record keeps the whole result,
unclipped, so anything the project later claims to have learned can be traced
back to the run that taught it. The harness writes it -- there is no tool, so
nothing depends on a model remembering to remember.
"""

import json
from dataclasses import replace

import pytest

from conftest import EXAMPLES
from poieo.binding import BindingSpec
from poieo.cli import _task_payload
from poieo.daemon.config import load_config, load_flows
from poieo.errors import SpecError
from poieo.graph import GraphSpec, NodeSpec
from poieo.providers import ProviderPool
from poieo.runtime.context import RunResult
from poieo.runtime.executor import execute
from poieo.store import RunStore
from poieo.memory import check_memory, load_facts
from poieo.task import JOURNAL_WIDTH, load_task, record_run, system_block

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
    memory = tmp_path / "tasks" / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "constitution.md").write_text(text, encoding="utf-8")
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
    assert "memory" not in _task_payload(task)

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
    block = _task_payload(task)["memory"]
    assert "Never push to main." in block


def test_an_edit_takes_effect_next_run_without_reload(tmp_path):
    _task(tmp_path)
    memory = _remember(tmp_path)
    flow, config = _daemon_flow(tmp_path)
    assert "Never push to main." in flow.read_input(config)["memory"]

    (memory / "constitution.md").write_text("Ship one change at a time.", encoding="utf-8")
    assert "Ship one change at a time." in flow.read_input(config)["memory"]


def test_a_malformed_fact_fails_at_load_naming_the_file(tmp_path):
    _task(tmp_path)
    facts = _remember(tmp_path) / "facts"
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
        block = _task_payload(task)["memory"]

    assert long_page.strip() in block
    assert any("trim" in message for message in caplog.messages)


def test_editor_notes_in_the_page_never_reach_the_prompt(tmp_path):
    task = _task(tmp_path)
    _remember(
        tmp_path,
        "<!-- ask the four questions before adding a line -->\nNever push to main.",
    )
    block = _task_payload(task)["memory"]
    assert "Never push to main." in block
    assert "four questions" not in block


def test_an_empty_memory_folder_behaves_as_absent(tmp_path):
    task = _task(tmp_path)
    (tmp_path / "tasks" / "memory").mkdir()

    assert system_block(task) == TODAY_WITHOUT_MEMORY.format(
        name=task.name, folder=task.folder_path()
    )
    assert "memory" not in _task_payload(task)


# -- entries naming each other -----------------------------------------------
#
# A connection is a judgment and lives in the files: prose mentions never
# fail anything, typed claims validate at load like every other spec poieo
# reads.


def _learn(tmp_path, slug, text):
    facts = tmp_path / "tasks" / "memory" / "facts"
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


def test_leaning_on_a_set_aside_entry_is_legal_at_load(tmp_path):
    _learn(tmp_path, "new-cap", "Batches cap at 500 now.")
    _learn(tmp_path, "old-cap", "---\nsuperseded_by: new-cap\n---\nBatches cap at 50.")
    project = _learn(
        tmp_path, "retry", "---\nlinks:\n  depends_on: [old-cap]\n---\nRetry once."
    )
    check_memory(project)  # legal; the report will flag it, nothing breaks
