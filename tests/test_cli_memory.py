"""`poieo memory` answers "what would this task see, and why?" without
touching anything. A person writes through three commands of their own --
`keep`, `set-aside`, `page` -- and the lookup machinery rebuilds itself, so
no command exists for that.
"""

from conftest import at, remember
from test_card import write_card
from typer.testing import CliRunner

from poieo.card import load_card
from poieo.cli import app
from poieo.memory import entry_named, history_of, read_memory, read_page, write_page

runner = CliRunner()


def _project(tmp_path):
    path = write_card(tmp_path, "importer", "name: mind the importer\nprompt: review the api batches\n")
    project = tmp_path / "tasks"
    write_page(project, "Never push to main.")
    remember(project, "batch-cap", "The api rejects batches over 50.")
    remember(project, "old-cap", "---\nsuperseded_by: batch-cap\n---\nThe api rejects batches over 10.")
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
    block = read_memory(project, load_card(card))
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
    write_card(tmp_path, "importer", "name: mind the importer\nprompt: go\n")
    result = runner.invoke(app, ["memory", str(tmp_path / "tasks")])

    assert result.exit_code == 0
    assert "no memory" in result.stdout


# -- what the connections imply ----------------------------------------------


def _entry(project, slug, text):
    remember(project, slug, text)


def test_memory_lists_a_disagreement_once(tmp_path):
    _, project = _project(tmp_path)
    _entry(project, "wild-claim", "Nothing ever gets refused.")
    _entry(
        project,
        "measured-claim",
        "---\nlinks:\n  contradicts: [wild-claim]\n---\nRefusals happen nightly.",
    )

    result = runner.invoke(app, ["memory", str(project)])
    assert result.exit_code == 0
    assert result.stdout.count("disagree") == 1
    assert "measured-claim" in result.stdout and "wild-claim" in result.stdout


def test_memory_flags_a_lean_on_a_set_aside_entry(tmp_path):
    _, project = _project(tmp_path)
    # old-cap is already set aside in the shared project; lean on it.
    _entry(
        project,
        "retry-note",
        "---\nlinks:\n  depends_on: [old-cap]\n---\nRetry once, past the cap.",
    )

    result = runner.invoke(app, ["memory", str(project)])
    assert result.exit_code == 0
    assert "second look" in result.stdout
    assert "retry-note" in result.stdout and "old-cap" in result.stdout


def test_a_memory_with_nothing_to_say_adds_no_sections(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["memory", str(project)])

    assert result.exit_code == 0
    assert "disagree" not in result.stdout
    assert "second look" not in result.stdout


def test_learn_runs_one_pass_and_says_what_it_kept(tmp_path):
    import json

    _, project = _project(tmp_path)
    episodes = at(project).results()
    episodes.mkdir(parents=True)
    (episodes / "20260824T010000-aaaaaaaa.json").write_text(
        json.dumps(
            {
                "run_id": "20260824T010000-aaaaaaaa",
                "task": "importer",
                "status": "completed",
                "summary": "imported the feeds",
            }
        ),
        encoding="utf-8",
    )
    binding = tmp_path / "learner.yaml"
    binding.write_text(
        "name: mock\n"
        "providers:\n"
        "  fake:\n"
        "    type: mock\n"
        "    options:\n"
        "      responses:\n"
        '        learner: \'{"entries": [{"slug": "feed-cap", "body": '
        '"Feeds cap at 50."}], "set_aside": []}\'\n'
        "default: {provider: fake, model: mock-model}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["learn", str(project), "-b", str(binding)])
    assert result.exit_code == 0
    assert "kept" in result.stdout and "feed-cap" in result.stdout
    assert entry_named(project, "feed-cap") is not None


def test_learn_says_when_there_is_nothing_to_read(tmp_path):
    _, project = _project(tmp_path)
    binding = tmp_path / "learner.yaml"
    binding.write_text(
        "name: mock\nproviders: {fake: {type: mock}}\ndefault: {provider: fake, model: mock-model}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["learn", str(project), "-b", str(binding)])
    assert result.exit_code == 0
    assert "nothing new" in result.stdout


def test_learn_without_memory_says_how_to_start_and_exits_zero(tmp_path):
    write_card(tmp_path, "importer", "name: mind the importer\nprompt: go\n")
    binding = tmp_path / "learner.yaml"
    binding.write_text(
        "name: mock\nproviders: {fake: {type: mock}}\ndefault: {provider: fake, model: mock-model}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["learn", str(tmp_path / "tasks"), "-b", str(binding)])
    assert result.exit_code == 0
    assert "no memory" in result.stdout


def _aged(path, seconds_ago):
    """Anchored files are still files, so they still age by their mtime."""
    import os
    import time

    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))


def _backdate(project, seconds_ago, slug=None):
    """Move an entry, or the page, back in time the way waiting would."""
    import sqlite3
    from datetime import datetime, timedelta, timezone

    when = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(timespec="seconds")
    con = sqlite3.connect(at(project).longterm())
    if slug is None:
        con.execute("UPDATE page SET updated_at = ? WHERE only = 1", (when,))
    else:
        con.execute("UPDATE entries SET updated_at = ? WHERE slug = ?", (when, slug))
    con.commit()
    con.close()


def test_a_gone_anchor_earns_a_second_look(tmp_path):
    _, project = _project(tmp_path)
    _entry(
        project,
        "feeds-note",
        "---\nanchors: ['notebook/feeds.md']\n---\nFeeds land in one file.",
    )

    result = runner.invoke(app, ["memory", str(project)])
    assert "second look" in result.stdout
    assert "feeds-note" in result.stdout and "gone" in result.stdout


def test_a_target_changed_after_the_entry_earns_a_second_look(tmp_path):
    _, project = _project(tmp_path)
    target = project / "notebook"
    target.mkdir()
    (target / "feeds.md").write_text("feeds", encoding="utf-8")
    _entry(
        project,
        "feeds-note",
        "---\nanchors: ['notebook/feeds.md']\n---\nFeeds land in one file.",
    )
    _backdate(project, 3600, "feeds-note")

    result = runner.invoke(app, ["memory", str(project)])
    assert "feeds-note" in result.stdout and "changed after" in result.stdout


def test_touching_the_entry_clears_the_changed_after_line(tmp_path):
    _, project = _project(tmp_path)
    target = project / "notebook"
    target.mkdir()
    (target / "feeds.md").write_text("feeds", encoding="utf-8")
    _entry(
        project,
        "feeds-note",
        "---\nanchors: ['notebook/feeds.md']\n---\nFeeds land in one file.",
    )
    _aged(target / "feeds.md", 3600)  # older than the entry: looked at, then written

    result = runner.invoke(app, ["memory", str(project)])
    assert "changed after" not in result.stdout


def test_a_healthy_memory_reports_no_doubts(tmp_path):
    _, project = _project(tmp_path)
    target = project / "notebook"
    target.mkdir()
    (target / "feeds.md").write_text("feeds", encoding="utf-8")
    _entry(
        project,
        "feeds-note",
        "---\nanchors: ['notebook/feeds.md']\n---\nFeeds land in one file.",
    )
    _aged(target / "feeds.md", 3600)

    result = runner.invoke(app, ["memory", str(project)])
    assert "second look" not in result.stdout


def test_memory_shows_the_last_suggestion_and_only_the_last(tmp_path):
    import json

    _, project = _project(tmp_path)
    log = at(project).cache()
    log.mkdir(parents=True)
    lines = [
        {"at": "t1", "read": 1, "upto": "a", "error": None, "page": "Old idea."},
        {"at": "t2", "read": 1, "upto": "b", "error": None, "page": None},
    ]
    at(project).learning_log().write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    quiet = runner.invoke(app, ["memory", str(project)])
    assert "suggests" not in quiet.stdout

    with at(project).learning_log().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": "t3", "read": 1, "upto": "c", "error": None, "page": "New idea."}) + "\n")
    result = runner.invoke(app, ["memory", str(project)])
    assert "the last pass suggests: New idea." in result.stdout
    assert "Old idea" not in result.stdout


def _sealed_entry(tmp_path):
    from poieo.blob import store

    _, project = _project(tmp_path)
    notebook = project / "notebook"
    notebook.mkdir()
    target = notebook / "feeds.md"
    target.write_text("# feeds\n- a\n", encoding="utf-8")
    name = store(project, target)
    _entry(
        project,
        "feeds-note",
        "---\nanchors: ['notebook/feeds.md']\n"
        f'sealed: {{"notebook/feeds.md": "{name}"}}\n---\nFeeds land in one file.',
    )
    _backdate(project, 3600, "feeds-note")
    return project, target, name


def test_a_touched_but_identical_sealed_anchor_raises_nothing(tmp_path):
    project, target, _ = _sealed_entry(tmp_path)
    target.write_text("# feeds\n- a\n", encoding="utf-8")  # touched, identical

    result = runner.invoke(app, ["memory", str(project)])
    assert "second look" not in result.stdout


def test_changed_content_raises_the_no_longer_matches_line(tmp_path):
    project, target, _ = _sealed_entry(tmp_path)
    target.write_text("# feeds\n- a\n- b\n", encoding="utf-8")

    result = runner.invoke(app, ["memory", str(project)])
    assert "no longer matches" in result.stdout and "feeds-note" in result.stdout


def test_updating_the_entry_clears_a_sealed_doubt(tmp_path):
    # The documented gesture -- look, then touch -- must work for sealed
    # anchors too: a person who revised the entry for the new content
    # should not be nagged until they hand-compute a digest.
    project, target, _ = _sealed_entry(tmp_path)
    target.write_text("# feeds\n- a\n- b\n", encoding="utf-8")
    changed = runner.invoke(app, ["memory", str(project)])
    assert "no longer matches" in changed.stdout

    # The person reads the doubt and updates the entry (its file is now
    # newer than the changed target).
    _aged(target, 7200)
    result = runner.invoke(app, ["memory", str(project)])
    assert "no longer matches" not in result.stdout
    assert "second look" not in result.stdout


def test_a_lost_keepsake_falls_back_to_the_mtime_line(tmp_path):
    project, target, name = _sealed_entry(tmp_path)
    (at(project).blobs() / name).unlink()
    target.write_text("# feeds\n- a\n", encoding="utf-8")  # touched after the entry

    result = runner.invoke(app, ["memory", str(project)])
    assert "changed after it was written" in result.stdout
    assert "no longer matches" not in result.stdout


def _record_run(project, run_id, summary, shown, status="completed"):
    import json

    episodes = at(project).results()
    episodes.mkdir(parents=True, exist_ok=True)
    (episodes / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "task": "importer", "status": status, "summary": summary, "shown": shown}),
        encoding="utf-8",
    )


def test_memory_counts_the_runs_that_used_what_they_were_shown(tmp_path):
    _, project = _project(tmp_path)
    _entry(project, "cap-note", "The feed api rejects batches over fifty exactly.")
    _record_run(project, "20260824T010000-aaaaaaaa", "split the batches at fifty for the api", ["cap-note"])
    _record_run(project, "20260824T020000-bbbbbbbb", "nothing worth doing tonight", ["cap-note"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "kept in mind  1 of 2 recent runs used what they were shown" in result.stdout


def test_an_entry_shown_often_but_never_used_is_named(tmp_path):
    _, project = _project(tmp_path)
    _entry(project, "zebra-note", "Zebra ordering holds on holidays.")
    for i in range(3):
        _record_run(project, f"20260824T0{i}0000-aaaaaaa{i}", "nothing worth doing tonight", ["zebra-note"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "unused" in result.stdout
    assert "zebra-note (shown 3 times, used never)" in result.stdout


def test_an_entry_used_even_once_is_not_named(tmp_path):
    _, project = _project(tmp_path)
    _entry(project, "zebra-note", "Zebra ordering holds on holidays.")
    for i in range(3):
        _record_run(project, f"20260824T0{i}0000-aaaaaaa{i}", "nothing worth doing tonight", ["zebra-note"])
    _record_run(project, "20260824T040000-aaaaaaa4", "held the zebra ordering through the holidays", ["zebra-note"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "unused" not in result.stdout


def test_a_set_aside_entry_is_not_named_it_was_already_judged(tmp_path):
    _, project = _project(tmp_path)
    # old-cap is set aside in the shared project; old records showed it often.
    for i in range(4):
        _record_run(project, f"20260824T0{i}0000-aaaaaaa{i}", "nothing worth doing tonight", ["old-cap"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "unused" not in result.stdout


def test_a_vanished_entry_is_not_named_however_often_shown(tmp_path):
    _, project = _project(tmp_path)
    for i in range(4):
        _record_run(project, f"20260824T0{i}0000-aaaaaaa{i}", "nothing worth doing tonight", ["long-gone"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "unused" not in result.stdout


def test_a_project_without_records_shows_no_accounting(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["memory", str(project)])
    assert "kept in mind" not in result.stdout and "unused" not in result.stdout


def test_memory_is_still_read_only_with_connections(tmp_path):
    _, project = _project(tmp_path)
    _entry(
        project,
        "measured-claim",
        "---\nlinks:\n  contradicts: [batch-cap]\n---\nRefusals happen nightly.",
    )
    before = sorted(str(p) for p in project.rglob("*"))

    result = runner.invoke(app, ["memory", str(project)])
    assert result.exit_code == 0
    assert sorted(str(p) for p in project.rglob("*")) == before
    assert not (project / ".poieo").exists()


def test_editing_the_page_clears_the_suggestion(tmp_path):
    import json

    _, project = _project(tmp_path)
    log = at(project).cache()
    log.mkdir(parents=True)
    at(project).learning_log().write_text(
        json.dumps(
            {"at": "2026-08-20T00:00:00+00:00", "read": 1, "upto": "a", "error": None, "page": "Require ISO dates."}
        )
        + "\n",
        encoding="utf-8",
    )
    # The page is untouched since long before the pass: the suggestion shows.
    _backdate(project, 30 * 86400)
    shown = runner.invoke(app, ["memory", str(project)])
    assert "Require ISO dates." in shown.stdout

    # The person edits the page (fresh mtime): they have seen it -- clears.
    write_page(project, "Never push to main.\nDates are ISO.")
    result = runner.invoke(app, ["memory", str(project)])
    assert "Require ISO dates." not in result.stdout


# -- a person's three writes -------------------------------------------------


def test_keep_writes_an_entry_a_person_owns(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["keep", "feeds-order", "Feeds are imported oldest first.", "--in", str(project)])

    assert result.exit_code == 0, result.output
    assert "kept feeds-order" in result.stdout
    entry = entry_named(project, "feeds-order")
    assert entry.body == "Feeds are imported oldest first."
    assert entry.matter.source == []
    assert history_of(project, "feeds-order")[0]["writer"] == "person"


def test_keep_says_scope_anchors_and_connections_in_the_products_words(tmp_path):
    _, project = _project(tmp_path)
    (project / "notebook").mkdir()
    (project / "notebook" / "feeds.md").write_text("# feeds\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "keep", "feeds-order", "Oldest first.", "--in", str(project),
            "--scope", "importer", "--anchor", "notebook/feeds.md",
            "--leans-on", "batch-cap", "--disagrees-with", "old-cap",
        ],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    entry = entry_named(project, "feeds-order")
    assert entry.matter.scope == ["importer"]
    assert entry.matter.anchors == ["notebook/feeds.md"]
    assert entry.matter.links.depends_on == ["batch-cap"]
    assert entry.matter.links.contradicts == ["old-cap"]
    assert set(entry.matter.sealed) == {"notebook/feeds.md"}


def test_keep_refuses_a_connection_to_nothing_and_writes_nothing(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["keep", "leaner", "Leans on air.", "--in", str(project), "--leans-on", "ghost"])

    assert result.exit_code == 1
    assert "ghost" in result.output
    assert entry_named(project, "leaner") is None


def test_set_aside_marks_an_entry_for_its_replacement(tmp_path):
    _, project = _project(tmp_path)
    remember(project, "new-cap", "The api rejects batches over 500.")
    result = runner.invoke(app, ["set-aside", "batch-cap", "--because", "new-cap", "--in", str(project)])

    assert result.exit_code == 0, result.output
    assert "set aside batch-cap" in result.stdout
    assert entry_named(project, "batch-cap").matter.superseded_by == "new-cap"
    line = history_of(project, "batch-cap")[0]
    assert (line["writer"], line["did"]) == ("person", "set aside")


def test_set_aside_refuses_a_replacement_that_does_not_exist(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["set-aside", "batch-cap", "--because", "ghost", "--in", str(project)])

    assert result.exit_code == 1
    assert "ghost" in result.output
    assert entry_named(project, "batch-cap").matter.superseded_by is None


def test_page_prints_the_page_as_written_comments_and_all(tmp_path):
    _, project = _project(tmp_path)
    write_page(project, "<!-- keep this short -->\nNever push to main.")
    result = runner.invoke(app, ["page", "--in", str(project)])

    assert result.exit_code == 0, result.output
    assert "<!-- keep this short -->\nNever push to main." in result.stdout


def test_page_from_a_file_replaces_the_page_as_a_person(tmp_path):
    _, project = _project(tmp_path)
    rules = tmp_path / "rules.md"
    rules.write_text("Dates are ISO.\n", encoding="utf-8")
    result = runner.invoke(app, ["page", "--from", str(rules), "--in", str(project)])

    assert result.exit_code == 0, result.output
    assert read_page(project) == "Dates are ISO."
    assert history_of(project)[0]["writer"] == "person"

    missing = runner.invoke(app, ["page", "--from", str(tmp_path / "nowhere.md"), "--in", str(project)])
    assert missing.exit_code == 1
    assert "nowhere.md" in missing.output
    assert read_page(project) == "Dates are ISO."


def test_page_from_a_dash_reads_stdin(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["page", "--from", "-", "--in", str(project)], input="Dates are ISO.\n")

    assert result.exit_code == 0, result.output
    assert read_page(project) == "Dates are ISO."


def test_page_edit_opens_an_editor_and_keeps_what_comes_back(tmp_path, monkeypatch):
    import click

    _, project = _project(tmp_path)
    seen = {}

    def fake_edit(text, **kwargs):
        seen["text"] = text
        return text + "\nDates are ISO.\n"

    monkeypatch.setattr(click, "edit", fake_edit)
    result = runner.invoke(app, ["page", "--edit", "--in", str(project)])

    assert result.exit_code == 0, result.output
    assert seen["text"] == "Never push to main."
    assert read_page(project) == "Never push to main.\nDates are ISO."


def _suggested(project, line="Require ISO dates."):
    import json

    at(project).cache().mkdir(parents=True, exist_ok=True)
    at(project).learning_log().write_text(
        json.dumps({"at": "2026-08-20T00:00:00+00:00", "read": 1, "upto": "a", "error": None, "page": line}) + "\n",
        encoding="utf-8",
    )
    _backdate(project, 30 * 86400)


def test_page_accept_adds_the_last_suggestion_as_a_line_and_clears_it(tmp_path):
    _, project = _project(tmp_path)
    _suggested(project)
    result = runner.invoke(app, ["page", "--accept", "--in", str(project)])

    assert result.exit_code == 0, result.output
    assert read_page(project) == "Never push to main.\nRequire ISO dates."
    assert "Require ISO dates." not in runner.invoke(app, ["memory", str(project)]).stdout


def test_page_dismiss_keeps_the_page_and_clears_the_suggestion(tmp_path):
    _, project = _project(tmp_path)
    _suggested(project)
    result = runner.invoke(app, ["page", "--dismiss", "--in", str(project)])

    assert result.exit_code == 0, result.output
    assert read_page(project) == "Never push to main."
    assert "Require ISO dates." not in runner.invoke(app, ["memory", str(project)]).stdout


def test_page_accept_with_nothing_suggested_says_so(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["page", "--accept", "--in", str(project)])

    assert result.exit_code == 1
    assert "suggested nothing" in result.output
    assert read_page(project) == "Never push to main."


def test_page_takes_one_verb_at_a_time(tmp_path):
    _, project = _project(tmp_path)
    result = runner.invoke(app, ["page", "--accept", "--dismiss", "--in", str(project)])

    assert result.exit_code == 1
    assert "one of" in result.output


def test_writes_where_no_memory_is_kept_say_how_to_start(tmp_path):
    write_card(tmp_path, "importer", "name: mind the importer\nprompt: go\n")
    project = tmp_path / "tasks"
    for args in (
        ["keep", "a", "Something."],
        ["set-aside", "a", "--because", "b"],
        ["page", "--from", "-"],
    ):
        result = runner.invoke(app, [*args, "--in", str(project)], input="x\n")
        assert result.exit_code == 1, args
        assert "poieo init" in result.output
    assert not at(project).longterm().exists()


def _log_passes(project, *lines):
    import json

    log = at(project).learning_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")


def test_memory_reports_what_the_last_pass_did_and_let_go(tmp_path):
    _, project = _project(tmp_path)
    _log_passes(
        project,
        {"at": "2026-08-20T00:00:00+00:00", "read": 3, "upto": "a", "kept": ["older-one"], "error": None},
        {
            "at": "2026-08-21T03:00:00+00:00",
            "read": 2,
            "upto": "b",
            "kept": ["batch-cap"],
            "set_aside": ["old-cap"],
            "dropped": ["'bad slug': not a plain slug"],
            "error": None,
        },
    )

    result = runner.invoke(app, ["memory", str(project)])

    assert result.exit_code == 0
    assert "last pass    2026-08-21T03:00:00+00:00, read 2 records" in result.stdout
    assert "  kept       batch-cap" in result.stdout
    assert "  set aside  old-cap" in result.stdout
    assert "  let go     'bad slug': not a plain slug" in result.stdout
    assert "older-one" not in result.stdout


def test_memory_says_when_the_last_pass_failed(tmp_path):
    _, project = _project(tmp_path)
    _log_passes(
        project,
        {"at": "2026-08-21T03:00:00+00:00", "read": 4, "upto": None, "error": "ValueError: no JSON object"},
    )

    result = runner.invoke(app, ["memory", str(project)])

    assert result.exit_code == 0
    assert (
        "last pass    2026-08-21T03:00:00+00:00, read 4 records, failed and will reread: ValueError: no JSON object"
        in result.stdout
    )


def test_a_pass_that_learned_nothing_says_so_in_one_line(tmp_path):
    _, project = _project(tmp_path)
    _log_passes(project, {"at": "2026-08-21T03:00:00+00:00", "read": 1, "upto": "a", "error": None})

    result = runner.invoke(app, ["memory", str(project)])

    assert "last pass    2026-08-21T03:00:00+00:00, read 1 record, kept nothing" in result.stdout
    assert "  kept" not in result.stdout
