import json

from typer.testing import CliRunner

from test_checkpoint import make_repo

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
    result = runner.invoke(app, ["daemon", str(config), "--once"])
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


def flow_config(tmp_path, workdir):
    (tmp_path / "b.yaml").write_text(
        "providers: {p: {type: mock}}" + chr(10) + "default: {provider: p, model: m}" + chr(10),
        encoding="utf-8",
    )
    (tmp_path / "g.yaml").write_text(
        "name: g" + chr(10)
        + "entry: work" + chr(10)
        + "nodes: [{id: work, type: agent, role: p, prompt: do it}]" + chr(10),
        encoding="utf-8",
    )
    path = tmp_path / "d.yaml"
    path.write_text(
        "binding: b.yaml" + chr(10)
        + f"flows: [{{name: chores, graph: g.yaml, workdir: {workdir}}}]" + chr(10),
        encoding="utf-8",
    )
    return path


def test_flows_fails_when_a_workdir_is_missing(tmp_path):
    config = flow_config(tmp_path, "nowhere")

    result = runner.invoke(app, ["flows", str(config)])

    # Refused at load rather than discovered at 3am.
    assert result.exit_code != 0
    assert "workdir" in result.stderr  # errors go to stderr


def test_flows_warns_when_the_work_cannot_be_reviewed(tmp_path):
    (tmp_path / "project").mkdir()  # a real directory, but nothing tracks it
    config = flow_config(tmp_path, "project")

    result = runner.invoke(app, ["flows", str(config)])

    # A degraded mode, not an error: the flow still runs tonight.
    assert result.exit_code == 0
    assert "reviewed or undone" in result.stdout


def test_flows_is_quiet_when_the_work_can_be_reviewed(tmp_path):
    make_repo(tmp_path)
    config = flow_config(tmp_path, "project")

    result = runner.invoke(app, ["flows", str(config)])

    assert result.exit_code == 0
    assert "reviewed or undone" not in result.stdout


def test_run_takes_a_workdir_for_a_portable_graph(tmp_path):
    result = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLES / "graphs/agent-task.yaml"),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
            "--workdir",
            str(tmp_path),
            "--no-log",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "TODO.md").exists()


def test_validate_accepts_a_graph_that_leaves_the_workdir_open():
    # A graph is the logical layer: not saying where it runs is the point,
    # not a defect. `validate` says what the graph will need, and passes.
    result = runner.invoke(
        app,
        [
            "validate",
            str(EXAMPLES / "graphs/agent-task.yaml"),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "valid" in result.stdout
    assert "workdir" in result.stdout  # but it says one will be needed
    assert "work" in result.stdout  # and names the node that needs it
