"""Every task run leaves one full record behind.

The journal keeps one line per run; the record keeps the whole result,
unclipped, so anything the project later claims to have learned can be traced
back to the run that taught it. The harness writes it -- there is no tool, so
nothing depends on a model remembering to remember.
"""

import json
from dataclasses import replace

from poieo.binding import BindingSpec
from poieo.graph import GraphSpec, NodeSpec
from poieo.providers import ProviderPool
from poieo.runtime.context import RunResult
from poieo.runtime.executor import execute
from poieo.store import RunStore
from poieo.task import JOURNAL_WIDTH, load_task, record_run

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
