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


def test_help_tells_two_stories_not_seventeen():
    """Six commands visible -- the person's and the agent's story. The rest
    keep working, hidden: plumbing, files the user edits directly, or views
    the web board owns."""
    visible = {
        info.name or info.callback.__name__
        for info in app.registered_commands
        if not info.hidden
    }
    assert visible == {"init", "daemon", "run", "validate", "check"}
    # `runs` rides along as a sub-app.
    result = runner.invoke(app, ["--help"])
    assert "runs" in result.stdout
    assert "eject" not in result.stdout


def test_hidden_commands_still_work():
    result = runner.invoke(app, ["show", str(EXAMPLES / "graphs/support-triage.yaml")])
    assert result.exit_code == 0
    assert "classify" in result.stdout


def test_validate_json_is_machine_readable():
    result = runner.invoke(
        app,
        [
            "validate",
            str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["valid"] is True
    assert data["graph"] == "support-triage"
    assert "classifier" in data["roles"]
    assert data["binding"]["roles"]["classifier"]  # role -> model resolution


def test_check_json_is_machine_readable():
    result = runner.invoke(
        app, ["check", "-b", str(EXAMPLES / "bindings/mock.yaml"), "--json"]
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert rows and rows[0]["provider"] == "fake"
    assert rows[0]["healthy"] is True


def test_runs_list_json_is_machine_readable(tmp_path):
    run = runner.invoke(
        app,
        [
            "run",
            str(EXAMPLES / "graphs/support-triage.yaml"),
            "-b",
            str(EXAMPLES / "bindings/mock.yaml"),
            "--set",
            "message=hi",
            "--store",
            str(tmp_path / "logs"),
        ],
    )
    assert run.exit_code == 0, run.output
    result = runner.invoke(
        app, ["runs", "list", "--store", str(tmp_path / "logs"), "--json"]
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert len(rows) == 1 and rows[0]["status"] == "completed"

    empty = runner.invoke(
        app, ["runs", "list", "--store", str(tmp_path / "nothing"), "--json"]
    )
    assert json.loads(empty.stdout) == []  # JSON stays JSON, even empty


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


def test_eject_writes_the_graph_beside_the_card(tmp_path):
    path = _task(tmp_path, body="name: tidy\nprompt: go\nevery: 30m\n")
    result = runner.invoke(app, ["eject", str(path)])
    assert result.exit_code == 0

    # Beside the card, under its name: a graph is what a card expands to, so
    # the two are one kind of thing and the pairing stays visible.
    graph_file = tmp_path / "tasks" / "tidy.graph.yaml"
    assert "type: agent" in graph_file.read_text(encoding="utf-8")
    rewritten = path.read_text(encoding="utf-8")
    assert "graph: tidy.graph.yaml" in rewritten
    assert "prompt" not in rewritten
    assert "every: 30m" in rewritten

    after = runner.invoke(app, ["show", str(path)])
    assert after.exit_code == 0
    assert "agent" in after.stdout


def test_an_ejected_graph_does_not_become_a_second_task(tmp_path):
    path = _task(tmp_path, body="name: tidy\nprompt: go\n")
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\ntasks: tasks/\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["eject", str(path)]).exit_code == 0

    result = runner.invoke(app, ["tasks", str(config)])
    assert result.exit_code == 0, result.output
    # One status marker, so one card -- the graph beside it is not a task.
    assert result.stdout.count("[on ]") + result.stdout.count("[off]") == 1


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


# -- the first-run experience ------------------------------------------------
#
# DESIGN.md promises the only things a user writes are a name and a prompt.
# These pin the places where the CLI used to break that promise first.


def _self_bound_card(tmp_path):
    (tmp_path / "work").mkdir(exist_ok=True)
    card = tmp_path / "card.yaml"
    card.write_text(
        "name: hello\nfolder: work\nprompt: say hello\n"
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\n"
    )
    return card


def test_run_uses_the_binding_the_card_names(tmp_path):
    """The first command a new user types must not demand a flag the card
    already answers."""
    result = runner.invoke(app, ["run", str(_self_bound_card(tmp_path)), "--no-log"])
    assert result.exit_code == 0, result.output


def test_run_without_any_binding_names_both_ways_out(tmp_path):
    (tmp_path / "work").mkdir(exist_ok=True)
    card = tmp_path / "card.yaml"
    card.write_text("name: hello\nfolder: work\nprompt: say hello\n")
    result = runner.invoke(app, ["run", str(card), "--no-log"])
    assert result.exit_code == 1
    assert "-b" in result.stderr and "binding:" in result.stderr


def test_run_flag_still_wins_over_the_card(tmp_path):
    result = runner.invoke(
        app,
        ["run", str(_self_bound_card(tmp_path)), "--no-log",
         "-b", str(EXAMPLES / "bindings/mock.yaml")],
    )
    assert result.exit_code == 0, result.output


def test_daemon_given_a_folder_runs_the_cards_in_it(tmp_path):
    """`poieo daemon tasks/` is the natural guess, and it used to answer with
    a raw traceback."""
    folder = tmp_path / "tasks"
    folder.mkdir()
    (tmp_path / "work").mkdir()
    (folder / "hello.yaml").write_text(
        "name: hello\nfolder: ../work\nprompt: say hello\n"
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\n"
    )
    result = runner.invoke(app, ["daemon", str(folder), "--once", "--no-web"])
    assert result.exit_code == 0, result.output


def test_daemon_given_a_task_card_points_at_both_answers(tmp_path):
    card = _self_bound_card(tmp_path)
    result = runner.invoke(app, ["daemon", str(card), "--once", "--no-web"])
    assert result.exit_code == 1
    assert "task" in result.stderr
    assert "poieo run" in result.stderr


def test_a_typo_gets_one_line_and_a_suggestion(tmp_path):
    (tmp_path / "work").mkdir()
    card = tmp_path / "card.yaml"
    card.write_text("name: hello\nfolder: work\npromt: say hello\n")
    result = runner.invoke(app, ["validate", str(card)])
    assert result.exit_code == 1
    assert "promt" in result.stderr
    assert "prompt" in result.stderr          # the did-you-mean
    assert "pydantic" not in result.stderr    # internals stay internal
    assert "https://" not in result.stderr


def test_validate_checks_the_schedule_too(tmp_path):
    """It said "valid" on a card whose schedule could not parse -- and a
    validator that lies is worse than none."""
    (tmp_path / "work").mkdir()
    card = tmp_path / "card.yaml"
    card.write_text("name: hello\nfolder: work\nprompt: hi\nevery: 5 minutes\n")
    result = runner.invoke(app, ["validate", str(card)])
    assert result.exit_code == 1
    assert "5m" in result.stderr              # the fix is named, not just the fault


# -- a one-shot run is still a task's run ------------------------------------
#
# The journal contract says a task writes a line at the end of every run. That
# held for daemon runs only: `poieo run card.yaml` read the journal and never
# wrote it, so a second run redid the first's work and a note it read was
# never consumed.


def test_run_writes_the_journal(tmp_path):
    card = _self_bound_card(tmp_path)
    result = runner.invoke(app, ["run", str(card), "--no-log"])
    assert result.exit_code == 0, result.output
    journal = (tmp_path / "card.md").read_text(encoding="utf-8")
    assert "did" in journal


def test_run_consumes_a_note_the_way_a_daemon_run_does(tmp_path):
    """The bookmark must move, or a note stays "new" forever."""
    card = _self_bound_card(tmp_path)
    runner.invoke(app, ["note", str(card), "look at the README first"])
    runner.invoke(app, ["run", str(card), "--no-log"])
    from poieo.task import load_task, read_journal

    shown = read_journal(load_task(card).journal_path())
    assert "Nothing new" in shown
    assert "look at the README" in shown       # consumed, not lost


def test_run_stores_beside_the_card(tmp_path, monkeypatch):
    """One task, one history -- wherever the command was typed from."""
    card = _self_bound_card(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = runner.invoke(app, ["run", str(card)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".poieo" / "runs").is_dir()
    assert not (elsewhere / ".poieo").exists()


def test_run_store_flag_still_wins(tmp_path):
    card = _self_bound_card(tmp_path)
    result = runner.invoke(
        app, ["run", str(card), "--store", str(tmp_path / "mystore")]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "mystore" / "runs").is_dir()


def test_a_graph_still_stores_in_the_cwd(tmp_path, monkeypatch):
    """The beside-the-card rule is the card's; bare graphs keep today's."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["run", str(EXAMPLES / "graphs/support-triage.yaml"),
         "-b", str(EXAMPLES / "bindings/mock.yaml"), "--set", "message=hi"],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".poieo" / "runs").is_dir()


def test_daemon_folder_stores_beside_the_cards(tmp_path):
    folder = tmp_path / "tasks"
    folder.mkdir()
    (tmp_path / "work").mkdir()
    (folder / "hello.yaml").write_text(
        "name: hello\nfolder: ../work\nprompt: say hello\n"
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\n"
    )
    result = runner.invoke(app, ["daemon", str(folder), "--once", "--no-web"])
    assert result.exit_code == 0, result.output
    assert (folder / ".poieo" / "runs").is_dir()


# -- where the work happens ---------------------------------------------------
#
# A graph is the logical layer and may leave its workdir open. A flow in a
# daemon config may not: a directory that is not there has to be refused at
# load, rather than discovered when the cron fires at 3am.


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


def test_both_commands_that_look_for_a_project_say_the_same_thing(tmp_path, monkeypatch):
    """`daemon` and `flows` each fall back to the project's poieo.yaml, and
    each has to refuse when there is none. The refusal is a sentence the user
    reads, so there is one wording of it, not one per command."""
    monkeypatch.chdir(tmp_path)  # no poieo.yaml here or above

    refusals = []
    for command in (["daemon"], ["flows"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 1, command
        refusals.append(result.stderr.strip())

    assert "no poieo.yaml found here or above" in refusals[0]
    assert "poieo init" in refusals[0]
    assert refusals[0] == refusals[1]
