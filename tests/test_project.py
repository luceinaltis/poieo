"""A folder becomes a project the way a folder becomes a git repository:
one marker file, found by walking up."""

import json
from pathlib import Path

import pytest

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


# -- poieo init ---------------------------------------------------------------


def _no_machine(monkeypatch):
    """A machine with nothing on it: no key, no ollama."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import poieo.project as project

    monkeypatch.setattr(project, "_ollama_models", lambda: [])


def test_init_on_a_bare_machine_defaults_to_mock(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    default = (tmp_path / "bindings" / "default.yaml").read_text(encoding="utf-8")
    assert "mock" in default
    # The last lines orient the user: the next two commands to type.
    assert "poieo run tasks/hello.yaml" in result.stdout
    assert "poieo daemon" in result.stdout


def test_an_initialized_project_loads_and_runs_offline(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    from poieo.daemon import load_config

    config = load_config(tmp_path / "poieo.yaml")  # a project that cannot load is an init bug
    assert config.binding == "bindings/default.yaml"
    result = runner.invoke(app, ["run", "tasks/hello.yaml"])
    assert result.exit_code == 0, result.output
    assert "completed" in result.stdout


def test_init_with_an_api_key_writes_a_claude_binding(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    default = (tmp_path / "bindings" / "default.yaml").read_text(encoding="utf-8")
    assert "anthropic" in default


def test_init_with_ollama_writes_a_binding_naming_an_installed_model(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    import poieo.project as project

    monkeypatch.setattr(project, "_ollama_models", lambda: ["llama3.2:3b"])
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    default = (tmp_path / "bindings" / "default.yaml").read_text(encoding="utf-8")
    assert "ollama" in default
    assert "llama3.2:3b" in default


def test_init_twice_keeps_every_existing_file(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    before = {
        p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert "wrote" not in result.stdout
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_init_writes_the_agents_manual(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    manual = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    # The loop an agent must know: edit a file, then prove it loads.
    assert "poieo validate" in manual
    assert "poieo run" in manual
    assert ".poieo/" in manual
    # Claude Code loads the same page through its own file.
    assert "@AGENTS.md" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")


def test_init_never_touches_an_existing_claude_md(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    ours = "# my rules\nnever push on friday\n"
    (tmp_path / "CLAUDE.md").write_text(ours, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == ours
    # The manual itself still arrives; only the user's file is sacred.
    assert (tmp_path / "AGENTS.md").exists()


def test_init_appends_to_gitignore_without_clobbering_it(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["init"]).exit_code == 0
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "node_modules/" in lines
    assert lines.count(".poieo/") == 1


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


# -- a project is its paths, read no deeper ----------------------------------


def _project_with_cards(root, *, card_body="name: {n}\nfolder: .\nprompt: do {n}\n"):
    (root / "tasks").mkdir(parents=True, exist_ok=True)
    (root / "bindings").mkdir(parents=True, exist_ok=True)
    (root / "bindings" / "b.yaml").write_text(
        "providers: {p: {type: mock}}\ndefault: {provider: p, model: m}\n"
    )
    (root / "poieo.yaml").write_text(
        "version: 1\nstore: .poieo\nbinding: bindings/b.yaml\ntasks: tasks/\n"
    )
    for name in ("alpha", "beta", "gamma"):
        (root / "tasks" / f"{name}.yaml").write_text(card_body.format(n=name))
    return root


def test_finding_a_project_does_not_read_its_cards(tmp_path, monkeypatch):
    """Discovery answers "where is the store" and "which binding". It used to
    parse every card in the folder, cross-check the memory and build a graph
    per task to do it -- on `poieo run`, `poieo runs list`, everything."""
    import poieo.task as task_module

    _project_with_cards(tmp_path)

    parsed = []
    real = task_module.load_task
    monkeypatch.setattr(
        task_module, "load_task", lambda p: parsed.append(Path(p).name) or real(p)
    )

    project = find_project(tmp_path)

    assert parsed == []
    assert project is not None
    assert project.store_path() == tmp_path / ".poieo"
    assert project.binding == "bindings/b.yaml"


def test_a_card_with_a_typo_no_longer_breaks_an_unrelated_command(tmp_path, monkeypatch):
    """A broken card is the daemon's business. It used to fail `poieo runs
    list`, which never looks at a card, because discovery loaded them all."""
    _project_with_cards(tmp_path, card_body="name: {n}\nfolder: .\npromt: oops\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0
    assert "no runs recorded" in result.stdout

    # The daemon still refuses, naming the card and the typo.
    refused = runner.invoke(app, ["flows"])
    assert refused.exit_code == 1
    assert "promt" in refused.stderr


def test_a_broken_marker_still_fails_wherever_it_is_consulted(tmp_path):
    from poieo.errors import SpecError

    _mark(tmp_path, "version: 1\nstoer: logs\n")  # a typo in the marker itself
    with pytest.raises(SpecError, match="store"):
        find_project(tmp_path)


def test_the_daemon_config_is_a_project_and_reads_the_same_keys(tmp_path):
    """One schema, extended -- so `store` cannot mean one thing to `poieo run`
    and another to `poieo daemon`."""
    from poieo.daemon.config import DaemonConfig, load_config
    from poieo.project import ProjectSpec, load_project

    _project_with_cards(tmp_path)
    marker = tmp_path / "poieo.yaml"

    assert issubclass(DaemonConfig, ProjectSpec)
    shallow, full = load_project(marker), load_config(marker)
    assert shallow.store_path() == full.store_path()
    assert shallow.resolve_path("x") == full.resolve_path("x")
    assert (shallow.binding, shallow.tasks) == (full.binding, full.tasks)
    # ...and only the full load expands the cards into flows.
    assert [f.name for f in full.flows] == ["alpha", "beta", "gamma"]
    assert shallow.flows == []
