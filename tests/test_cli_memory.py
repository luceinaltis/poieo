"""`poieo memory` answers "what would this task see, and why?" without
touching anything. Authoring stays with the editor and git; rebuilding the
lookup machinery is automatic, so no command exists for either.
"""

from conftest import at
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
    memory = at(tmp_path / "tasks")
    memory.facts().mkdir(parents=True)
    memory.constitution().write_text("Never push to main.", encoding="utf-8")
    (memory.facts() / "batch-cap.md").write_text(
        "The api rejects batches over 50.\n", encoding="utf-8"
    )
    (memory.facts() / "old-cap.md").write_text(
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


# -- what the connections imply ----------------------------------------------


def _entry(project, slug, text):
    (at(project).facts() / f"{slug}.md").write_text(text, encoding="utf-8")


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
        "        learner: '{\"entries\": [{\"slug\": \"feed-cap\", \"body\": "
        "\"Feeds cap at 50.\"}], \"set_aside\": []}'\n"
        "default: {provider: fake, model: mock-model}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["learn", str(project), "-b", str(binding)])
    assert result.exit_code == 0
    assert "kept" in result.stdout and "feed-cap" in result.stdout
    assert (at(project).facts() / "feed-cap.md").is_file()


def test_learn_says_when_there_is_nothing_to_read(tmp_path):
    _, project = _project(tmp_path)
    binding = tmp_path / "learner.yaml"
    binding.write_text(
        "name: mock\nproviders: {fake: {type: mock}}\n"
        "default: {provider: fake, model: mock-model}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["learn", str(project), "-b", str(binding)])
    assert result.exit_code == 0
    assert "nothing new" in result.stdout


def test_learn_without_memory_says_how_to_start_and_exits_zero(tmp_path):
    write_task(tmp_path, "importer", "name: mind the importer\nprompt: go\n")
    binding = tmp_path / "learner.yaml"
    binding.write_text(
        "name: mock\nproviders: {fake: {type: mock}}\n"
        "default: {provider: fake, model: mock-model}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["learn", str(tmp_path / "tasks"), "-b", str(binding)])
    assert result.exit_code == 0
    assert "no memory" in result.stdout


def _aged(path, seconds_ago):
    import os
    import time

    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))


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
    _aged(at(project).facts() / "feeds-note.md", 3600)

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
    at(project).learning_log().write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )
    quiet = runner.invoke(app, ["memory", str(project)])
    assert "suggests" not in quiet.stdout

    with at(project).learning_log().open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"at": "t3", "read": 1, "upto": "c", "error": None, "page": "New idea."}
            )
            + "\n"
        )
    result = runner.invoke(app, ["memory", str(project)])
    assert "the last pass suggests: New idea." in result.stdout
    assert "Old idea" not in result.stdout


def _sealed_entry(tmp_path):
    from poieo.blob import keep

    _, project = _project(tmp_path)
    notebook = project / "notebook"
    notebook.mkdir()
    target = notebook / "feeds.md"
    target.write_text("# feeds\n- a\n", encoding="utf-8")
    name = keep(project, target)
    _entry(
        project,
        "feeds-note",
        "---\nanchors: ['notebook/feeds.md']\n"
        f'sealed: {{"notebook/feeds.md": "{name}"}}\n---\nFeeds land in one file.',
    )
    _aged(at(project).facts() / "feeds-note.md", 3600)
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
        json.dumps(
            {"run_id": run_id, "task": "importer", "status": status,
             "summary": summary, "shown": shown}
        ),
        encoding="utf-8",
    )


def test_memory_counts_the_runs_that_used_what_they_were_shown(tmp_path):
    _, project = _project(tmp_path)
    _entry(project, "cap-note", "The feed api rejects batches over fifty exactly.")
    _record_run(project, "20260824T010000-aaaaaaaa",
                "split the batches at fifty for the api", ["cap-note"])
    _record_run(project, "20260824T020000-bbbbbbbb",
                "nothing worth doing tonight", ["cap-note"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "kept in mind  1 of 2 recent runs used what they were shown" in result.stdout


def test_an_entry_shown_often_but_never_used_is_named(tmp_path):
    _, project = _project(tmp_path)
    _entry(project, "zebra-note", "Zebra ordering holds on holidays.")
    for i in range(3):
        _record_run(project, f"20260824T0{i}0000-aaaaaaa{i}",
                    "nothing worth doing tonight", ["zebra-note"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "unused" in result.stdout
    assert "zebra-note (shown 3 times, used never)" in result.stdout


def test_an_entry_used_even_once_is_not_named(tmp_path):
    _, project = _project(tmp_path)
    _entry(project, "zebra-note", "Zebra ordering holds on holidays.")
    for i in range(3):
        _record_run(project, f"20260824T0{i}0000-aaaaaaa{i}",
                    "nothing worth doing tonight", ["zebra-note"])
    _record_run(project, "20260824T040000-aaaaaaa4",
                "held the zebra ordering through the holidays", ["zebra-note"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "unused" not in result.stdout


def test_a_set_aside_entry_is_not_named_it_was_already_judged(tmp_path):
    _, project = _project(tmp_path)
    # old-cap is set aside in the shared project; old records showed it often.
    for i in range(4):
        _record_run(project, f"20260824T0{i}0000-aaaaaaa{i}",
                    "nothing worth doing tonight", ["old-cap"])

    result = runner.invoke(app, ["memory", str(project)])
    assert "unused" not in result.stdout


def test_a_vanished_entry_is_not_named_however_often_shown(tmp_path):
    _, project = _project(tmp_path)
    for i in range(4):
        _record_run(project, f"20260824T0{i}0000-aaaaaaa{i}",
                    "nothing worth doing tonight", ["long-gone"])

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
            {"at": "2026-08-20T00:00:00+00:00", "read": 1, "upto": "a",
             "error": None, "page": "Require ISO dates."}
        )
        + "\n",
        encoding="utf-8",
    )
    # The page is untouched since long before the pass: the suggestion shows.
    _aged(at(project).constitution(), 30 * 86400)
    shown = runner.invoke(app, ["memory", str(project)])
    assert "Require ISO dates." in shown.stdout

    # The person edits the page (fresh mtime): they have seen it -- clears.
    at(project).constitution().write_text(
        "Never push to main.\nDates are ISO.", encoding="utf-8"
    )
    result = runner.invoke(app, ["memory", str(project)])
    assert "Require ISO dates." not in result.stdout
