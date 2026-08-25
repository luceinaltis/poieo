"""A folder becomes a project the way a folder becomes a git repository:
one marker file, found by walking up."""

import json

from typer.testing import CliRunner

from poieo.cli import app
from poieo.project import find_project, find_project_file

runner = CliRunner()


def _mark(folder, body="version: 1\n"):
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / "poieo.yaml"
    marker.write_text(body, encoding="utf-8")
    return marker


def test_marker_in_the_start_dir_is_found(tmp_path):
    marker = _mark(tmp_path)
    assert find_project_file(tmp_path) == marker


def test_marker_in_a_parent_is_found_from_below(tmp_path):
    marker = _mark(tmp_path)
    below = tmp_path / "tasks" / "deep"
    below.mkdir(parents=True)
    assert find_project_file(below) == marker


def test_no_marker_anywhere_means_no_project(tmp_path):
    assert find_project_file(tmp_path) is None
    assert find_project(tmp_path) is None


def test_the_nearest_marker_wins(tmp_path):
    _mark(tmp_path)
    inner = _mark(tmp_path / "sub")
    assert find_project_file(tmp_path / "sub") == inner


def test_find_project_loads_the_config_it_found(tmp_path):
    _mark(tmp_path, "version: 1\nstore: logs\n")
    config = find_project(tmp_path)
    assert config is not None
    assert config.store_path() == tmp_path / "logs"


# -- the runs commands stop demanding --store --------------------------------


def test_runs_list_without_store_outside_a_project_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["runs", "list"])
    assert result.exit_code == 0
    # The product's voice, never a traceback -- and the message names where
    # it looked, so an empty answer is still an informative one.
    assert "no runs recorded" in result.stdout
    assert ".poieo" in result.stdout
    assert "TypeError" not in result.stdout


def test_runs_list_without_store_reads_the_projects_store(tmp_path, monkeypatch):
    _mark(tmp_path, "version: 1\nstore: logs\n")
    index = tmp_path / "logs" / "runs" / "index.jsonl"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps({"run_id": "r-1", "status": "completed", "steps": 3}) + "\n",
        encoding="utf-8",
    )
    below = tmp_path / "tasks"
    below.mkdir()
    monkeypatch.chdir(below)
    result = runner.invoke(app, ["runs", "list"])
    assert result.exit_code == 0
    assert "r-1" in result.stdout


def test_runs_show_without_store_reads_the_projects_store(tmp_path, monkeypatch):
    _mark(tmp_path, "version: 1\nstore: logs\n")
    log = tmp_path / "logs" / "runs" / "r-2.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        json.dumps({"run_id": "r-2", "type": "run_started", "at": "t0"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["runs", "show", "r-2"])
    assert result.exit_code == 0
    assert "run_started" in result.stdout


# -- commands read the project file ------------------------------------------

_MOCK = """\
name: mock
providers:
  fake:
    type: mock
    options:
      responses: {{"*": "{answer}"}}
default: {{provider: fake, model: mock-model}}
"""


def _project(tmp_path, answer="done"):
    """A minimal project: a marker naming a default binding, and one card."""
    (tmp_path / "bindings").mkdir(exist_ok=True)
    (tmp_path / "bindings" / "mock.yaml").write_text(
        _MOCK.format(answer=answer), encoding="utf-8"
    )
    (tmp_path / "poieo.yaml").write_text(
        "version: 1\nbinding: bindings/mock.yaml\n", encoding="utf-8"
    )
    card = tmp_path / "tasks" / "hello.yaml"
    card.parent.mkdir(exist_ok=True)
    card.write_text("name: hello\nfolder: .\nprompt: say hi\n", encoding="utf-8")
    return card


def test_run_takes_the_projects_binding_and_says_so(tmp_path, monkeypatch):
    card = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", str(card)])
    assert result.exit_code == 0, result.output
    # Automatic is fine, invisible is not: the filled-in default names itself.
    assert "(from" in result.stdout
    assert "poieo.yaml" in result.stdout


def test_run_inside_a_project_logs_into_the_projects_store(tmp_path, monkeypatch):
    card = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", str(card)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".poieo" / "runs" / "index.jsonl").exists()
    # One history, not two: the run log lands in the project store, never
    # beside the card. (Episodes stay beside the card -- the memory system
    # reads them there, and that is a different record.)
    assert not (card.parent / ".poieo" / "runs").exists()


def test_the_binding_flag_still_beats_the_project(tmp_path, monkeypatch):
    card = _project(tmp_path, answer="from-project")
    flagged = tmp_path / "flag.yaml"
    flagged.write_text(_MOCK.format(answer="from-flag"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", str(card), "-b", str(flagged)])
    assert result.exit_code == 0, result.output
    assert "from-flag" in result.stdout
    assert "(from" not in result.stdout


def test_the_cards_own_binding_still_beats_the_project(tmp_path, monkeypatch):
    card = _project(tmp_path, answer="from-project")
    (tmp_path / "tasks" / "own.yaml").write_text(
        _MOCK.format(answer="from-card"), encoding="utf-8"
    )
    card.write_text(
        "name: hello\nfolder: .\nprompt: say hi\nbinding: own.yaml\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", str(card)])
    assert result.exit_code == 0, result.output
    assert "from-card" in result.stdout


def test_run_outside_a_project_still_fails_in_the_products_voice(tmp_path, monkeypatch):
    card = tmp_path / "hello.yaml"
    card.write_text("name: hello\nfolder: .\nprompt: say hi\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", str(card)])
    assert result.exit_code == 1
    assert "no binding" in result.stderr
    assert "poieo.yaml" in result.stderr


def test_validate_reports_a_project_supplied_binding(tmp_path, monkeypatch):
    card = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate", str(card)])
    assert result.exit_code == 0, result.output
    assert "binding" in result.stdout
    assert "(from" in result.stdout


def test_check_probes_the_projects_binding_without_a_flag(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "ok" in result.stdout


def test_check_outside_a_project_fails_in_the_products_voice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "no binding" in result.stderr


def test_daemon_without_an_argument_uses_the_project(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["daemon", "--once", "--no-web"])
    assert result.exit_code == 0, result.output


def test_daemon_without_an_argument_outside_a_project_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["daemon", "--once", "--no-web"])
    assert result.exit_code == 1
    assert "poieo.yaml" in result.stderr


def test_flows_without_an_argument_uses_the_project(tmp_path, monkeypatch):
    _project(tmp_path)
    (tmp_path / "g.yaml").write_text(
        "name: g\nentry: a\nnodes: [{id: a, type: llm, role: r, prompt: hi}]\n",
        encoding="utf-8",
    )
    marker = tmp_path / "poieo.yaml"
    marker.write_text(
        marker.read_text(encoding="utf-8")
        + "flows:\n  - {name: f, graph: g.yaml}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["flows"])
    assert result.exit_code == 0, result.output
    assert "f" in result.stdout


def test_the_store_flag_still_wins_over_the_project(tmp_path, monkeypatch):
    _mark(tmp_path, "version: 1\nstore: logs\n")
    elsewhere = tmp_path / "elsewhere"
    index = elsewhere / "runs" / "index.jsonl"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps({"run_id": "r-3", "status": "completed", "steps": 1}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["runs", "list", "--store", str(elsewhere)])
    assert result.exit_code == 0
    assert "r-3" in result.stdout
