"""Writing to the memory, and what each write leaves behind.

The database is the only copy now, so the promises that used to belong to git
belong here: nothing is written without a line saying who wrote it, a shape
from the future is refused rather than guessed at, and one project's memory
never reaches another's.
"""

import sqlite3

import pytest
from conftest import at

from poieo.errors import SpecError
from poieo.memory import (
    check_memory,
    entry_named,
    frontmatter,
    history_of,
    keeps_memory,
    page_written_at,
    read_page,
    readable_entries,
    set_aside,
    start_memory,
    write_entry,
    write_page,
)


def _project(tmp_path, name="tasks"):
    project = tmp_path / name
    project.mkdir(parents=True, exist_ok=True)
    (project / "poieo.yaml").write_text("version: 1\n", encoding="utf-8")
    return project


def test_no_database_means_no_memory_at_all(tmp_path):
    """The file is the whole opt-in: nothing creates it on the way past, and a
    project without one shows no trace of the feature."""
    project = _project(tmp_path)

    assert keeps_memory(project) is False
    assert readable_entries(project) == []
    assert read_page(project) is None
    assert history_of(project) == []
    check_memory(project)  # must not raise
    assert not at(project).longterm().exists()


def test_an_entry_reads_back_as_it_was_written(tmp_path):
    project = _project(tmp_path)
    write_entry(
        project,
        "batch-cap",
        "The api rejects batches over 50; keep [[feeds-order]] in mind.",
        frontmatter({"scope": ["importer"], "anchors": ["notebook"], "source": ["r1"]}),
    )

    entry = entry_named(project, "batch-cap")
    assert entry.body == "The api rejects batches over 50; keep [[feeds-order]] in mind."
    assert entry.matter.scope == ["importer"]
    assert entry.matter.anchors == ["notebook"]
    assert entry.matter.source == ["r1"]
    assert entry.mentions == ["feeds-order"]
    assert [e.slug for e in readable_entries(project)] == ["batch-cap"]


def test_every_write_leaves_a_line_saying_who(tmp_path):
    project = _project(tmp_path)
    write_entry(project, "cap", "Batches stop at 50.", writer="pass")
    write_entry(project, "cap", "Batches stop at 500.", writer="person")

    lines = history_of(project, "cap")
    assert [(line["writer"], line["did"]) for line in lines] == [("person", "wrote"), ("pass", "wrote")]
    assert lines[0]["before"] == {"body": "Batches stop at 50."}
    assert lines[0]["after"] == {"body": "Batches stop at 500."}
    assert lines[1]["before"] is None


def test_a_name_that_could_escape_is_refused(tmp_path):
    project = _project(tmp_path)
    for bad in ("../outside", "Cap", "with space", "", "-leading"):
        with pytest.raises(SpecError):
            write_entry(project, bad, "Something.")


def test_setting_aside_keeps_the_body_and_says_so(tmp_path):
    project = _project(tmp_path)
    write_entry(project, "old-cap", "Batches stop at 10.")
    write_entry(project, "new-cap", "Batches stop at 50.")

    set_aside(project, "old-cap", "new-cap", writer="pass")

    entry = entry_named(project, "old-cap")
    assert entry.body == "Batches stop at 10."
    assert entry.matter.superseded_by == "new-cap"
    line = history_of(project, "old-cap")[0]
    assert (line["writer"], line["did"]) == ("pass", "set aside")
    assert line["after"] == {"superseded_by": "new-cap"}


def test_the_page_is_read_without_its_comments(tmp_path):
    project = _project(tmp_path)
    write_page(project, "<!-- a note to whoever edits this -->\n- Never write outside the notebook.")

    assert read_page(project) == "- Never write outside the notebook."
    assert page_written_at(project) is not None
    assert history_of(project)[0]["did"] == "page"


def test_a_memory_from_a_newer_poieo_is_refused_not_guessed(tmp_path):
    """Losing the only copy is unrecoverable, so a shape this code does not
    understand stops rather than being migrated on a guess."""
    project = _project(tmp_path)
    start_memory(project)
    con = sqlite3.connect(at(project).longterm())
    con.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    con.commit()
    con.close()

    with pytest.raises(SpecError, match="newer poieo"):
        entry_named(project, "anything")


def test_a_memory_of_the_older_shape_is_moved_forward_not_rebuilt(tmp_path):
    """The first real migration, and the promise the whole file rests on: a
    database written before pieces carried their shape keeps every word it had,
    gains the new column filled in, and answers the same questions afterwards."""
    project = _project(tmp_path)
    write_entry(project, "cap", "Refusing feeds are noted, never retried.")

    # Wind it back to the shape before this change: no `shape`, a lookup built
    # on the words themselves, and the older version stamped in.
    con = sqlite3.connect(at(project).longterm())
    con.executescript(
        "DROP TRIGGER pieces_after_insert; DROP TRIGGER pieces_after_delete;"
        "DROP TRIGGER pieces_after_update; DROP TABLE pieces_fts;"
        "CREATE TABLE old(id INTEGER PRIMARY KEY, slug TEXT, ord INTEGER, text TEXT, UNIQUE(slug, ord));"
        "INSERT INTO old SELECT id, slug, ord, text FROM pieces;"
        "DROP TABLE pieces; ALTER TABLE old RENAME TO pieces;"
        "UPDATE meta SET value = '1' WHERE key = 'schema_version';"
    )
    con.commit()
    con.close()

    # Opening it migrates, and nothing was thrown away to do it.
    entry = entry_named(project, "cap")
    assert entry.body == "Refusing feeds are noted, never retried."
    assert history_of(project, "cap")[0]["after"] == {"body": entry.body}

    con = sqlite3.connect(at(project).longterm())
    shape = con.execute("SELECT shape FROM pieces WHERE slug = 'cap'").fetchone()[0]
    version = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    con.close()
    assert "feed" in shape.split()  # the entry said "feeds"; the shape is what it matches by
    assert version == "2"


def test_an_entry_is_one_piece_today(tmp_path):
    """Retrieval matches pieces, not entries. One each for now -- the seam is
    what lets a long entry become several without moving the schema."""
    project = _project(tmp_path)
    write_entry(project, "cap", "Batches stop at 50.")

    con = sqlite3.connect(at(project).longterm())
    rows = con.execute("SELECT ord, text FROM pieces WHERE slug = 'cap'").fetchall()
    con.close()
    assert rows == [(0, "Batches stop at 50.")]


def test_two_projects_never_see_each_other(tmp_path):
    """One database per project, inside that project. The daemon holds several
    at once, and this is the leak that would matter most."""
    one = _project(tmp_path, "one")
    other = _project(tmp_path, "other")
    write_entry(one, "mine", "Only the first project knows this.")
    write_entry(other, "theirs", "Only the second project knows this.")

    assert [e.slug for e in readable_entries(one)] == ["mine"]
    assert [e.slug for e in readable_entries(other)] == ["theirs"]
    assert entry_named(one, "theirs") is None


def test_a_typed_claim_naming_nothing_fails_the_load(tmp_path):
    project = _project(tmp_path)
    write_entry(project, "leaner", "Leans on air.", frontmatter({"links": {"depends_on": ["ghost"]}}))

    with pytest.raises(SpecError, match="ghost"):
        check_memory(project)
