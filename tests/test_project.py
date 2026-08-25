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
