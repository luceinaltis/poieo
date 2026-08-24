"""`poieo memory` answers "what would this task see, and why?" without
touching anything. Authoring stays with the editor and git; rebuilding the
lookup machinery is automatic, so no command exists for either.
"""

from typer.testing import CliRunner

from poieo.cli import app
from poieo.memory import read_memory
from poieo.task import load_task

from test_task import write_task

runner = CliRunner()


def _project(tmp_path):
    path = write_task(
        tmp_path, "importer", "name: mind the importer\nprompt: review the api batches\n"
    )
    memory = tmp_path / "tasks" / "memory"
    (memory / "facts").mkdir(parents=True)
    (memory / "constitution.md").write_text("Never push to main.", encoding="utf-8")
    (memory / "facts" / "batch-cap.md").write_text(
        "The api rejects batches over 50.\n", encoding="utf-8"
    )
    (memory / "facts" / "old-cap.md").write_text(
        "---\nsuperseded_by: batch-cap\n---\nThe api rejects batches over 10.\n",
        encoding="utf-8",
    )
    return path, tmp_path / "tasks"


def test_memory_reports_page_size_counts_and_lookup(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["memory", str(project)])

    assert result.exit_code == 0
    assert "page" in result.stdout and "19 characters" in result.stdout
    assert "1 kept, 1 set aside" in result.stdout
    assert "lookup" in result.stdout


def test_memory_with_a_card_prints_exactly_what_the_run_would_see(tmp_path):
    card, project = _project(tmp_path)
    result = runner.invoke(app, ["memory", str(card)])

    assert result.exit_code == 0
    block = read_memory(project, load_task(card))
    assert block in result.stdout


def test_memory_is_read_only(tmp_path):
    card, project = _project(tmp_path)
    before = sorted(str(p) for p in project.rglob("*"))

    result = runner.invoke(app, ["memory", str(card)])
    assert result.exit_code == 0
    # No file mutated, and no lookup machinery left behind.
    assert sorted(str(p) for p in project.rglob("*")) == before
    assert not (project / ".poieo").exists()


def test_a_project_without_memory_says_so_plainly_and_exits_zero(tmp_path):
    write_task(tmp_path, "importer", "name: mind the importer\nprompt: go\n")
    result = runner.invoke(app, ["memory", str(tmp_path / "tasks")])

    assert result.exit_code == 0
    assert "no memory" in result.stdout
