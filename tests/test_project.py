"""A folder becomes a project the way a folder becomes a git repository:
one marker file, found by walking up."""

import json
from pathlib import Path

import pytest

from typer.testing import CliRunner

from conftest import card
from poieo import detect as detect_module
from poieo.cli import app
from poieo.detect import Engine
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
    assert "runs" in result.stdout
    assert "TypeError" not in result.stdout


def test_runs_list_without_store_reads_the_projects_store(tmp_path, monkeypatch):
    _mark(tmp_path, "version: 1\nstore: logs\n")
    index = tmp_path / "logs" / "index.jsonl"
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
    log = tmp_path / "logs" / "events" / "r-2.jsonl"
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
        "version: 1\nbinding: bindings/mock.yaml\ntasks: tasks\n", encoding="utf-8"
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
    assert (tmp_path / "runs" / "index.jsonl").exists()
    # One history, not two: the run log lands in the project store, never
    # beside the card. (Episodes stay beside the card -- the memory system
    # reads them there, and that is a different record.)
    assert not (card.parent / "runs").exists()


def test_a_runs_events_and_its_result_land_under_one_roof(tmp_path, monkeypatch):
    """Two halves of one account, keyed by the same run id. They are written
    by different code -- `RunStore` from the executor, `write_result` from
    `record_run` -- and if the two disagree about where `runs/` is, a
    learning pass can read one and not the other."""
    card = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["run", str(card)]).exit_code == 0

    events = list((tmp_path / "runs" / "events").glob("*.jsonl"))
    results = list((tmp_path / "runs" / "results").glob("*.json"))
    assert len(events) == 1 and len(results) == 1
    assert events[0].stem == results[0].stem


def test_store_moves_the_events_and_the_results_together(tmp_path, monkeypatch):
    card = _project(tmp_path)
    (tmp_path / "poieo.yaml").write_text(
        "version: 1\nbinding: bindings/mock.yaml\nstore: elsewhere\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["run", str(card)]).exit_code == 0

    assert list((tmp_path / "elsewhere" / "events").glob("*.jsonl"))
    assert list((tmp_path / "elsewhere" / "results").glob("*.json"))
    assert not (tmp_path / "runs").exists()


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
        "name: g\nentry: a\nnodes: [{id: a, type: agent, role: r, prompt: hi}]\n",
        encoding="utf-8",
    )
    marker = tmp_path / "poieo.yaml"
    card(tmp_path / "tasks", "f", "graph: ../g.yaml\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["flows"])
    assert result.exit_code == 0, result.output
    assert "f" in result.stdout


# -- poieo init ---------------------------------------------------------------


OLLAMA = Engine(
    key="ollama",
    label="Ollama",
    type="ollama",
    models=("qwen3:32b", "llama3.2:3b"),
    base_url="http://localhost:11434",
)
LMSTUDIO = Engine(
    key="lmstudio",
    label="LM Studio",
    type="openai_compatible",
    models=("qwen2.5-coder-7b",),
    base_url="http://localhost:1234/v1",
)
CLAUDE = Engine(
    key="claude",
    label="Claude API",
    type="anthropic",
    models=("claude-opus-5", "claude-haiku-4-5"),
)


def _machine_with(monkeypatch, *engines):
    """What detection finds on the machine running this test: exactly this.

    Patched on detect itself rather than on the CLI's name for it: the CLI is
    what asks -- detection returns a pool and the front end decides what to do
    with it -- but which module holds the reference is not what these tests
    are about.
    """
    monkeypatch.setattr(detect_module, "detect", lambda: list(engines))


def _no_machine(monkeypatch):
    """A machine with nothing on it: no key, no local server."""
    _machine_with(monkeypatch)


def test_init_on_a_bare_machine_refuses_instead_of_inventing_answers(tmp_path, monkeypatch):
    """mock answers from a script. Falling back to it silently would hand the
    user a project that runs all night and produces invented text."""
    _no_machine(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 1
    # Nothing half-written: the folder is exactly as it was found.
    assert list(tmp_path.iterdir()) == []
    # Names where it looked, and what to do about it.
    assert "Ollama" in result.stderr and "ANTHROPIC_API_KEY" in result.stderr
    assert "--mock" in result.stderr


def test_init_mock_is_the_deliberate_way_to_get_an_offline_project(tmp_path, monkeypatch):
    _no_machine(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "--mock"]).exit_code == 0
    from poieo.daemon import load_config

    config = load_config(tmp_path / "poieo.yaml")  # a project that cannot load is an init bug
    assert config.binding == "models/default.yaml"
    result = runner.invoke(app, ["run", "tasks/hello.yaml"])
    assert result.exit_code == 0, result.output
    assert "completed" in result.stdout


def test_every_engine_found_is_declared_so_a_role_can_name_it(tmp_path, monkeypatch):
    """The point of detection: a pool to bind roles against. A machine with
    two engines that could only ever use one of them is the reason roles
    existed and nobody could reach them."""
    _machine_with(monkeypatch, CLAUDE, OLLAMA, LMSTUDIO)
    monkeypatch.chdir(tmp_path)

    assert runner.invoke(app, ["init"]).exit_code == 0

    default = (tmp_path / "models" / "default.yaml").read_text(encoding="utf-8")
    for key in ("claude:", "ollama:", "lmstudio:"):
        assert key in default, key
    assert "base_url: http://localhost:11434" in default
    assert "base_url: http://localhost:1234/v1" in default
    # ...and every model each one reported, so naming one is reading, not
    # remembering.
    for model in ("qwen3:32b", "llama3.2:3b", "qwen2.5-coder-7b", "claude-opus-5"):
        assert model in default, model


def test_the_written_binding_resolves_every_engine_it_declares(tmp_path, monkeypatch):
    """Generated YAML that will not load is an init bug, and it should be
    caught here rather than on the project's first run."""
    from poieo.binding import load_binding

    _machine_with(monkeypatch, CLAUDE, OLLAMA, LMSTUDIO)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0

    binding = load_binding(tmp_path / "models" / "default.yaml")

    assert set(binding.providers) == {"claude", "ollama", "lmstudio"}
    # The default role resolves without the user editing a thing.
    assert binding.resolve("default").model in CLAUDE.models


def test_the_first_engine_found_becomes_the_default_unattended(tmp_path, monkeypatch):
    _machine_with(monkeypatch, OLLAMA, CLAUDE)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    from poieo.binding import load_binding

    binding = load_binding(tmp_path / "models" / "default.yaml")
    assert binding.default.provider == "ollama"
    assert binding.default.model == "qwen3:32b"


def test_init_says_which_engine_it_chose_and_why(tmp_path, monkeypatch):
    """Automatic is fine; invisible is not."""
    _machine_with(monkeypatch, OLLAMA)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert "Ollama" in result.stdout and "qwen3:32b" in result.stdout
    # The last lines orient the user: the next two commands to type.
    assert "poieo run tasks/hello.yaml" in result.stdout
    assert "poieo daemon" in result.stdout


def test_the_roles_example_shows_something_other_than_the_default():
    """An example that repeats the default teaches nothing, and the whole
    point of a role is that it can go somewhere else."""
    from poieo.project import binding_document

    # One engine, several models: the example has to move the model.
    document = binding_document([OLLAMA], ("ollama", "qwen3:32b"))
    example = document.split("#   roles:")[1]
    assert 'model: "llama3.2:3b"' in example

    # Two engines: the example moves the engine, which is the harder half.
    document = binding_document([OLLAMA, CLAUDE], ("ollama", "qwen3:32b"))
    example = document.split("#   roles:")[1]
    assert "provider: claude" in example


def test_a_long_model_id_survives_the_catalogue_whole():
    """The catalogue exists to be copied from. A name wrapped across two lines
    is worse than no name at all -- and real Ollama tags are long and full of
    the hyphens a text wrapper likes to break on."""
    from poieo.project import binding_document

    long_ones = (
        "hf.co/empero-ai/Qwen3.8-9B-Distill-GGUF:Q5_K_M",
        "hf.co/yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF:latest",
        "short:1b",
    )
    engine = Engine("ollama", "Ollama", "ollama", long_ones, "http://localhost:11434")

    document = binding_document([engine], ("ollama", "short:1b"))

    for model in long_ones:
        assert model in document, model


def test_a_single_model_machine_still_writes_a_loadable_binding(tmp_path, monkeypatch):
    """Nothing else to point an example at, and that must not crash."""
    from poieo.binding import load_binding

    only = Engine("ollama", "Ollama", "ollama", ("llama3.2:3b",), "http://localhost:11434")
    _machine_with(monkeypatch, only)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert load_binding(tmp_path / "models" / "default.yaml").resolve("default").model == (
        "llama3.2:3b"
    )


def test_mock_is_still_written_as_a_file_to_reach_for(tmp_path, monkeypatch):
    """Never the default, always available: `-b models/mock.yaml` is how the
    wiring gets exercised without spending a token."""
    _machine_with(monkeypatch, OLLAMA)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert (tmp_path / "models" / "mock.yaml").exists()
    assert "mock" not in (tmp_path / "models" / "default.yaml").read_text(encoding="utf-8")


def test_init_twice_keeps_every_existing_file(tmp_path, monkeypatch):
    _machine_with(monkeypatch, OLLAMA)
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
    _machine_with(monkeypatch, OLLAMA)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    manual = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    # The loop an agent must know: edit a file, then prove it loads.
    assert "poieo validate" in manual
    assert "poieo run" in manual
    # The layout, so an agent looks in the right folders.
    assert "models/" in manual
    assert "longterm/constitution.md" in manual
    assert "runs/" in manual and "memory/cache/" in manual
    # Claude Code loads the same page through its own file.
    assert "@AGENTS.md" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")


def test_init_never_touches_an_existing_claude_md(tmp_path, monkeypatch):
    _machine_with(monkeypatch, OLLAMA)
    ours = "# my rules\nnever push on friday\n"
    (tmp_path / "CLAUDE.md").write_text(ours, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == ours
    # The manual itself still arrives; only the user's file is sacred.
    assert (tmp_path / "AGENTS.md").exists()


def test_init_appends_to_gitignore_without_clobbering_it(tmp_path, monkeypatch):
    _machine_with(monkeypatch, OLLAMA)
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["init"]).exit_code == 0
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "node_modules/" in lines
    # Every line poieo needs, and each of them exactly once however many
    # times init is run.
    for ignored in ("memory/cache/", "runs/", "worktrees/"):
        assert lines.count(ignored) == 1, ignored


def test_the_store_flag_still_wins_over_the_project(tmp_path, monkeypatch):
    _mark(tmp_path, "version: 1\nstore: logs\n")
    elsewhere = tmp_path / "elsewhere"
    index = elsewhere / "index.jsonl"
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
        "version: 1\nstore: runs\nbinding: bindings/b.yaml\ntasks: tasks/\n"
    )
    for name in ("alpha", "beta", "gamma"):
        (root / "tasks" / f"{name}.yaml").write_text(card_body.format(n=name))
    return root


def test_finding_a_project_does_not_read_its_cards(tmp_path, monkeypatch):
    """Discovery answers "where is the store" and "which binding". It used to
    parse every card in the folder, cross-check the memory and build a graph
    per task to do it -- on `poieo run`, `poieo runs list`, everything."""
    import poieo.card as task_module

    _project_with_cards(tmp_path)

    parsed = []
    real = task_module.load_card
    monkeypatch.setattr(
        task_module, "load_card", lambda p: parsed.append(Path(p).name) or real(p)
    )

    project = find_project(tmp_path)

    assert parsed == []
    assert project is not None
    assert project.store_path() == tmp_path / "runs"
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
    assert (shallow.binding, shallow.cards) == (full.binding, full.cards)
    # ...and only the full load reads the cards into tasks.
    assert [f.name for f in full.tasks] == ["alpha", "beta", "gamma"]
    assert shallow.cards == full.cards  # the shallow read stops at the folder
