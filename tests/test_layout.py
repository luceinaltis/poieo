"""One module answers "what lives where", so a path is spelled once."""

from pathlib import Path

from poieo.layout import Layout, layout_for


def _mark(folder: Path, body: str = "version: 1\n") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / "poieo.yaml"
    marker.write_text(body, encoding="utf-8")
    return marker


# -- what counts as the root -------------------------------------------------


def test_without_a_marker_the_starting_folder_is_the_root(tmp_path):
    assert layout_for(tmp_path).root == tmp_path.resolve()


def test_a_marker_above_makes_its_folder_the_root(tmp_path):
    _mark(tmp_path)
    below = tmp_path / "tasks"
    below.mkdir()
    assert layout_for(below).root == tmp_path.resolve()


def test_the_nearest_marker_wins(tmp_path):
    _mark(tmp_path)
    _mark(tmp_path / "sub")
    assert layout_for(tmp_path / "sub").root == (tmp_path / "sub").resolve()


# -- the memory a person reads and edits -------------------------------------


def test_the_memory_a_person_keeps_hangs_off_the_root(tmp_path):
    layout = layout_for(tmp_path)
    root = tmp_path.resolve()
    assert layout.memory() == root / "memory"
    assert layout.shortterm() == root / "memory" / "shortterm"
    assert layout.longterm() == root / "memory" / "longterm"
    assert layout.constitution() == root / "memory" / "longterm" / "constitution.md"
    assert layout.facts() == root / "memory" / "longterm" / "facts"
    assert layout.attic() == root / "memory" / "longterm" / "attic"


def test_a_journal_is_named_for_its_task(tmp_path):
    layout = layout_for(tmp_path)
    assert layout.journal("chores") == layout.shortterm() / "chores.md"


# -- the memory only the machine reads ---------------------------------------


def test_what_the_machine_derives_sits_under_cache(tmp_path):
    layout = layout_for(tmp_path)
    cache = tmp_path.resolve() / "memory" / "cache"
    assert layout.cache() == cache
    assert layout.blobs() == cache / "blobs"
    assert layout.index() == cache / "index.sqlite3"
    assert layout.strength() == cache / "strength.json"
    assert layout.learning_log() == cache / "learning.jsonl"


# -- what a run leaves behind ------------------------------------------------


def test_a_run_leaves_its_events_and_its_result_side_by_side(tmp_path):
    layout = layout_for(tmp_path)
    runs = tmp_path.resolve() / "runs"
    assert layout.runs() == runs
    assert layout.run_index() == runs / "index.jsonl"
    assert layout.events() == runs / "events"
    assert layout.results() == runs / "results"


def test_worktrees_hang_off_the_root(tmp_path):
    assert layout_for(tmp_path).worktrees() == tmp_path.resolve() / "worktrees"


# -- store: moves the run history, and nothing else --------------------------


def test_store_moves_the_whole_run_history(tmp_path):
    _mark(tmp_path, "version: 1\nstore: logs\n")
    layout = layout_for(tmp_path)
    logs = tmp_path.resolve() / "logs"
    assert layout.runs() == logs
    assert layout.run_index() == logs / "index.jsonl"
    # The two records of one run travel together: they share a run id, and a
    # learning pass that could read one but not the other would be worse than
    # one that could read neither.
    assert layout.events() == logs / "events"
    assert layout.results() == logs / "results"


def test_store_leaves_the_memory_and_the_worktrees_where_they_are(tmp_path):
    _mark(tmp_path, "version: 1\nstore: logs\n")
    layout = layout_for(tmp_path)
    root = tmp_path.resolve()
    assert layout.memory() == root / "memory"
    assert layout.cache() == root / "memory" / "cache"
    # A private checkout is not a run log, however much it is written during
    # one, so pointing the logs elsewhere must not drag it along.
    assert layout.worktrees() == root / "worktrees"


def test_an_absolute_store_is_taken_as_written(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    _mark(tmp_path, f"version: 1\nstore: {elsewhere.as_posix()}\n")
    assert layout_for(tmp_path).events() == elsewhere / "events"


def test_a_store_the_document_never_names_still_lands_under_the_root(tmp_path):
    _mark(tmp_path)
    assert layout_for(tmp_path).runs() == tmp_path.resolve() / "runs"


# -- the plain constructor stays usable --------------------------------------


def test_a_layout_can_be_built_without_looking_at_the_disk(tmp_path):
    layout = Layout(root=tmp_path)
    assert layout.runs() == tmp_path / "runs"
    assert layout.facts() == tmp_path / "memory" / "longterm" / "facts"
