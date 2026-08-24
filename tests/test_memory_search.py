"""What a task is shown is chosen by what it is and where it works.

The index is derived and disposable -- delete it and nothing changes but
speed -- and the plain scan behind the same interface must return the same
entries, or the fallback is a different feature wearing the same name.
"""

import pytest

import poieo.memory as memory
from poieo.memory import read_memory
from poieo.task import load_task

from test_task import write_task


def _project(tmp_path, prompt="review the api batch sizes in the importer"):
    """A card, its folder, and a memory folder beside it."""
    path = write_task(tmp_path, "importer", f"name: mind the importer\nprompt: {prompt}\n")
    (tmp_path / "tasks" / "memory" / "facts").mkdir(parents=True)
    return load_task(path), tmp_path / "tasks"


def _fact(project, slug, body, matter=""):
    text = f"---\n{matter}\n---\n{body}\n" if matter else f"{body}\n"
    (project / "memory" / "facts" / f"{slug}.md").write_text(text, encoding="utf-8")


def test_a_relevant_entry_reaches_the_block(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")
    _fact(project, "unrelated", "The deploy pipeline reruns twice on Mondays.")

    block = read_memory(project, task)
    assert "What earlier work here has learned:" in block
    assert "The api rejects batch sizes over 50." in block
    assert "deploy pipeline" not in block


def test_the_fallback_returns_the_same_entries_as_fts(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")
    _fact(project, "retries", "The importer retries three times before giving up.")
    _fact(project, "unrelated", "The deploy pipeline reruns twice on Mondays.")

    preferred = read_memory(project, task)
    monkeypatch.setattr(memory, "_fts_available", lambda: False)
    assert read_memory(project, task) == preferred


def test_a_superseded_entry_never_surfaces(tmp_path):
    task, project = _project(tmp_path)
    _fact(
        project,
        "batch-cap",
        "The api rejects batch sizes over 50.",
        matter="superseded_by: batch-cap-raised",
    )
    _fact(project, "batch-cap-raised", "The api now accepts batch sizes up to 500.")

    block = read_memory(project, task)
    assert "up to 500" in block
    assert "over 50." not in block


def test_scope_admits_global_and_own_and_excludes_foreign(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "for-everyone", "Every api call here needs the batch header.", "scope: [global]")
    _fact(project, "for-me", "The importer api chokes on empty batch lists.", "scope: [importer]")
    _fact(project, "for-another", "The exporter api needs batch flushing.", "scope: [exporter]")

    block = read_memory(project, task)
    assert "needs the batch header" in block
    assert "chokes on empty batch lists" in block
    assert "exporter" not in block


def test_an_anchored_entry_outranks_a_merely_similar_one(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "anchored", "Watch the api batch limit here.", "anchors: ['../project']")
    _fact(project, "similar", "Another note about the api batch limit.")

    # Room for one entry only: rank decides who gets it.
    monkeypatch.setattr(memory, "FACTS_BUDGET", 40)
    block = read_memory(project, task)
    assert "Watch the api batch limit here." in block
    assert "Another note" not in block


def test_an_anchored_entry_arrives_even_without_a_shared_word(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "quirk", "Symlinks misbehave under WSL mounts.", "anchors: ['../project']")

    block = read_memory(project, task)
    assert "Symlinks misbehave" in block
    # And the slower lookup agrees, or it is a different feature.
    monkeypatch.setattr(memory, "_fts_available", lambda: False)
    assert read_memory(project, task) == block


def test_the_budget_cuts_whole_entries_and_spares_the_page(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    page = "Never push to main.\n" + "x" * 300
    (project / "memory" / "constitution.md").write_text(page, encoding="utf-8")
    _fact(project, "one", "The api batch importer note number one.")
    _fact(project, "two", "The api batch importer note number two.")

    monkeypatch.setattr(memory, "FACTS_BUDGET", 45)
    block = read_memory(project, task)
    # The page arrives whole however small the budget for learned entries is.
    assert page.strip() in block
    # One whole entry fits; the other is left out entirely, never half-shown.
    assert block.count("note number") == 1
    assert "number one." in block or "number two." in block


def test_a_deleted_index_is_rebuilt_silently(tmp_path):
    if not memory._fts_available():
        pytest.skip("this Python build has no FTS5, so there is no index file")
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")

    first = read_memory(project, task)
    index = project / ".poieo" / "memory.sqlite3"
    assert index.is_file()

    index.unlink()
    assert read_memory(project, task) == first
    assert index.is_file()


def test_nothing_is_ever_written_inside_the_memory_folder(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")
    before = sorted(p.name for p in (project / "memory").rglob("*"))

    read_memory(project, task)
    after = sorted(p.name for p in (project / "memory").rglob("*"))
    assert after == before
