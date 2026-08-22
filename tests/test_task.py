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
from poieo.task import TaskSpec, append_journal, expand, load_task, read_journal

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
    assert tail.startswith("(earlier entries omitted)")
    assert "entry 24" in tail and "entry 4" not in tail
    # The file itself keeps everything.
    assert "entry 0" in task.journal_path().read_text(encoding="utf-8")


def test_a_hand_written_line_is_read_like_any_other(tmp_path):
    task = load_task(write_task(tmp_path, "t", "name: t\nprompt: go\n"))
    task.journal_path().write_text("# t\n\nstop touching the README\n", encoding="utf-8")
    assert read_journal(task.journal_path()) == "stop touching the README"


def test_the_generated_prompt_carries_the_journal(tmp_path):
    _, graph = expand(load_task(write_task(tmp_path, "t", "name: t\nprompt: go\n")))
    assert "{{ input.journal }}" in graph.nodes[0].system


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
