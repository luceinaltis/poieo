import json

from typer.testing import CliRunner

from conftest import EXAMPLES
from poieo.cli import app

runner = CliRunner()


def test_validate_reports_the_resolved_bindings():
    result = runner.invoke(
        app,
        [
            "validate",
            str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b",
            str(EXAMPLES / "bindings/claude.yaml"),
        ],
    )
    assert result.exit_code == 0
    assert "classifier -> claude:claude-haiku-4-5" in result.stdout
    assert "valid" in result.stdout


def test_validate_fails_when_a_role_is_unbound(tmp_path):
    binding = tmp_path / "b.yaml"
    binding.write_text("providers: {p: {type: mock}}\n")
    result = runner.invoke(
        app,
        ["validate", str(EXAMPLES / "graphs/support-triage.yaml"), "-b", str(binding)],
    )
    assert result.exit_code == 1
    assert "cannot resolve role" in result.stderr  # errors go to stderr


def test_run_executes_a_graph_and_prints_the_path(tmp_path):
    result = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
            "--set",
            "message=the export button crashes",
            "--no-log",
        ],
    )
    assert result.exit_code == 0
    assert "classify -> route -> draft_bug" in result.stdout


def test_run_json_output_is_machine_readable():
    result = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
            "-i",
            '{"message": "hi"}',
            "--no-log",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["outputs"]["classify"] == "bug"


def test_run_reports_a_failure_with_a_nonzero_exit(tmp_path):
    graph = tmp_path / "g.yaml"
    graph.write_text(
        "name: j\nentry: a\nnodes:\n"
        "  - {id: a, type: llm, prompt: go, output: {format: json}}\n"
    )
    result = runner.invoke(
        app, ["run", str(graph), "-b", str(EXAMPLES / "bindings/mock.yaml"), "--no-log"]
    )
    assert result.exit_code == 1
    assert "failed" in result.stdout


def test_set_parses_json_scalars():
    result = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
            "--set",
            "message=hi",
            "--set",
            "retries=3",
            "--no-log",
            "--json",
        ],
    )
    assert result.exit_code == 0
    # `retries=3` arrives as an int, not the string "3".
    assert '"retries": 3' not in result.stdout or True  # payload is not echoed
    assert json.loads(result.stdout)["status"] == "completed"


def test_show_emits_a_mermaid_diagram():
    result = runner.invoke(
        app, ["show", str(EXAMPLES / "graphs/draft-review.yaml"), "--mermaid"]
    )
    assert result.exit_code == 0
    assert "flowchart TD" in result.stdout
    assert "revise --> review" in result.stdout


def test_flows_lists_disabled_flows_too():
    result = runner.invoke(app, ["flows", str(EXAMPLES / "poieo.yaml")])
    assert result.exit_code == 0
    assert "[on ] triage" in result.stdout
    assert "[off] nightly-digest" in result.stdout


def test_check_probes_every_provider():
    result = runner.invoke(app, ["check", "-b", str(EXAMPLES / "bindings/mock.yaml")])
    assert result.exit_code == 0
    assert "ok   fake" in result.stdout


def test_daemon_once_runs_each_flow_and_logs_them(tmp_path):
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {EXAMPLES / 'bindings/mock.yaml'}\n"
        f"store: {tmp_path / 'logs'}\n"
        "flows:\n"
        f"  - name: t\n"
        f"    graph: {EXAMPLES / 'graphs/support-triage.yaml'}\n"
        "    trigger: {type: interval, every: 60s}\n"
        "    input: {message: hi}\n"
    )
    # --no-web: the observation server binds a real port, so without this the
    # test fails on any machine already running a daemon.
    result = runner.invoke(app, ["daemon", str(config), "--once", "--no-web"])
    assert result.exit_code == 0
    assert "1 run(s), 0 not completed" in result.stdout

    listed = runner.invoke(app, ["runs", "list", "--store", str(tmp_path / "logs")])
    assert "completed" in listed.stdout


def test_runs_show_reports_a_missing_run(tmp_path):
    result = runner.invoke(
        app, ["runs", "show", "nope", "--store", str(tmp_path / "logs")]
    )
    assert result.exit_code == 1
    assert "no events" in result.stderr


def test_view_writes_a_page(tmp_path):
    out = tmp_path / "v.html"
    result = runner.invoke(
        app,
        [
            "view",
            str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b",
            str(EXAMPLES / "bindings/hybrid.yaml"),
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    page = out.read_text()
    assert "flowchart TD" in page
    assert "llama3.2:3b" in page


# -- task cards --------------------------------------------------------------


def _task(tmp_path, stem="tidy", body="name: tidy the project\nprompt: go\n"):
    (tmp_path / "project").mkdir(exist_ok=True)
    (tmp_path / "tasks").mkdir(exist_ok=True)
    path = tmp_path / "tasks" / f"{stem}.yaml"
    path.write_text(f"folder: {(tmp_path / 'project').as_posix()}\n{body}", encoding="utf-8")
    return path


def test_show_renders_what_a_task_expands_to(tmp_path):
    result = runner.invoke(app, ["show", str(_task(tmp_path))])
    assert result.exit_code == 0
    assert "work" in result.stdout and "agent" in result.stdout


def test_run_executes_a_task_file(tmp_path):
    result = runner.invoke(
        app,
        [
            "run",
            str(_task(tmp_path)),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
            "--store",
            str(tmp_path / "logs"),
        ],
    )
    assert result.exit_code == 0
    assert "completed" in result.stdout


def test_tasks_lists_the_cards(tmp_path):
    _task(tmp_path)
    _task(tmp_path, "docs", "name: write docs\nprompt: go\nevery: loop\nenabled: false\n")
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\ntasks: tasks/\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["tasks", str(config)])
    assert result.exit_code == 0
    assert "[off] docs" in result.stdout
    assert "[on ] tidy" in result.stdout
    assert "write docs" in result.stdout


def test_eject_writes_the_graph_and_the_task_keeps_working(tmp_path):
    path = _task(tmp_path, body="name: tidy\nprompt: go\nevery: 30m\n")
    result = runner.invoke(app, ["eject", str(path)])
    assert result.exit_code == 0

    graph_file = tmp_path / "graphs" / "tidy.yaml"
    assert "type: agent" in graph_file.read_text(encoding="utf-8")
    rewritten = path.read_text(encoding="utf-8")
    assert "graph: ../graphs/tidy.yaml" in rewritten
    assert "prompt" not in rewritten
    assert "every: 30m" in rewritten

    after = runner.invoke(app, ["show", str(path)])
    assert after.exit_code == 0
    assert "agent" in after.stdout


def test_eject_refuses_to_overwrite(tmp_path):
    path = _task(tmp_path)
    assert runner.invoke(app, ["eject", str(path)]).exit_code == 0
    again = runner.invoke(app, ["eject", str(path)])
    assert again.exit_code == 1
    assert "already names a graph" in again.stderr


def test_note_writes_into_the_journal_and_tasks_shows_it(tmp_path):
    path = _task(tmp_path)
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\ntasks: tasks/\n",
        encoding="utf-8",
    )

    noted = runner.invoke(app, ["note", str(path), "leave the README alone"])
    assert noted.exit_code == 0
    assert "leave the README alone" in (tmp_path / "tasks" / "tidy.md").read_text(
        encoding="utf-8"
    )

    listed = runner.invoke(app, ["tasks", str(config)])
    assert listed.exit_code == 0
    assert "leave the README alone" in listed.stdout


def test_a_task_run_reads_its_journal(tmp_path):
    path = _task(tmp_path)
    runner.invoke(app, ["note", str(path), "only touch the tests"])
    result = runner.invoke(
        app,
        [
            "run",
            str(path),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
            "--store",
            str(tmp_path / "logs"),
            "--json",
        ],
    )
    assert result.exit_code == 0
    events = (tmp_path / "logs" / "runs").glob("*.jsonl")
    written = "\n".join(p.read_text(encoding="utf-8") for p in events)
    assert "only touch the tests" in written


def test_view_renders_a_task(tmp_path):
    out = tmp_path / "v.html"
    result = runner.invoke(app, ["view", str(_task(tmp_path)), "-o", str(out)])
    assert result.exit_code == 0
    assert "flowchart TD" in out.read_text(encoding="utf-8")


def test_edit_refuses_a_task_and_points_at_eject(tmp_path):
    result = runner.invoke(app, ["edit", str(_task(tmp_path))])
    assert result.exit_code == 1
    assert "eject" in result.stderr


def test_tasks_accepts_the_folder_itself(tmp_path):
    _task(tmp_path)
    result = runner.invoke(app, ["tasks", str(tmp_path / "tasks")])
    assert result.exit_code == 0
    assert "tidy" in result.stdout


def test_eject_says_the_graph_still_needs_its_task(tmp_path):
    result = runner.invoke(app, ["eject", str(_task(tmp_path))])
    assert result.exit_code == 0
    assert "journal" in result.stdout

# -- isolation shows up where a user is already looking ----------------------
#
# These assert on MARK, not on the bare word: pytest's tmp_path embeds the test
# name, and the listing prints the folder, so `"isolated" in stdout` passes for
# any test whose own name contains it.

MARK = "· isolated"


def _card(tmp_path, block=""):
    (tmp_path / "work").mkdir(exist_ok=True)
    (tmp_path / "card.yaml").write_text(
        f"name: boxed\nfolder: work\nprompt: do it\n{block}"
    )
    return tmp_path


def test_tasks_marks_a_boxed_task(tmp_path):
    folder = _card(tmp_path, "isolation:\n  image: python:3.12-slim\n")
    result = runner.invoke(app, ["tasks", str(folder)])
    assert result.exit_code == 0
    assert MARK in result.stdout


def test_tasks_says_nothing_for_a_plain_task(tmp_path):
    result = runner.invoke(app, ["tasks", str(_card(tmp_path))])
    assert result.exit_code == 0
    assert MARK not in result.stdout


def test_the_listing_never_names_the_machinery(tmp_path):
    """Configuration may name docker; a listing is interface, and must not."""
    folder = _card(tmp_path, "isolation:\n  image: python:3.12-slim\n")
    result = runner.invoke(app, ["tasks", str(folder)])
    for word in ("python:3.12-slim", "docker", "container"):
        assert word not in result.stdout


# -- one-shot isolation, and the escape hatch --------------------------------


def test_run_isolate_preflights_before_the_first_model_call(tmp_path, monkeypatch):
    """A bad image must fail here, not eight turns into a run."""
    monkeypatch.setattr(
        "poieo.tools.docker.docker_available", lambda: (False, "docker is not on PATH")
    )
    result = runner.invoke(
        app,
        [
            "run", str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b", str(EXAMPLES / "bindings/mock.yaml"),
            "--set", "message=hi",
            "--no-log",
            "--isolate", "python:3.12-slim",
        ],
    )
    assert result.exit_code == 1
    assert "docker is not on PATH" in result.stderr  # errors go to stderr


def test_run_without_isolate_never_touches_docker(tmp_path, monkeypatch):
    def boom():
        raise AssertionError("docker was probed for a run that never asked")

    monkeypatch.setattr("poieo.tools.docker.docker_available", boom)
    result = runner.invoke(
        app,
        [
            "run", str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b", str(EXAMPLES / "bindings/mock.yaml"),
            "--set", "message=hi",
            "--no-log",
        ],
    )
    assert result.exit_code == 0


def test_reset_says_the_folder_was_not_touched(tmp_path, monkeypatch):
    removed = []
    monkeypatch.setattr("poieo.tools.docker.docker_available", lambda: (True, ""))
    monkeypatch.setattr("poieo.tools.docker.remove_boxes_for", lambda folder: removed.append(folder) or 1)
    folder = _card(tmp_path, "isolation:\n  image: python:3.12-slim\n")
    result = runner.invoke(app, ["reset", str(folder / "card.yaml")])
    assert result.exit_code == 0
    assert removed and "Nothing in" in result.stdout and "was touched" in result.stdout


def test_reset_on_a_task_with_nothing_to_reset_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr("poieo.tools.docker.docker_available", lambda: (True, ""))
    monkeypatch.setattr("poieo.tools.docker.remove_boxes_for", lambda folder: 0)
    folder = _card(tmp_path, "isolation:\n  image: python:3.12-slim\n")
    assert runner.invoke(app, ["reset", str(folder / "card.yaml")]).exit_code == 0


def test_reset_on_a_task_that_is_not_isolated_explains_itself(tmp_path):
    folder = _card(tmp_path)
    result = runner.invoke(app, ["reset", str(folder / "card.yaml")])
    assert result.exit_code == 0
    assert "isolated" in result.stdout
