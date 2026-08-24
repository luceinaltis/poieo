"""A pass reads the run records and writes down what stays true.

The model proposes; the harness writes. Every refusal here is the reason
the CLI and the daemon get to trust learn() completely: source ids are
stamped from the records actually shown, the bookmark moves only on
success, and one bad proposal never wastes the night's good entries.
"""

import json

from poieo.binding import BindingSpec
from poieo.learn import learn
from poieo.providers import ProviderPool

import poieo.learn as learning


def _project(tmp_path, page="Never push to main."):
    project = tmp_path / "tasks"
    (project / "memory" / "facts").mkdir(parents=True)
    if page is not None:
        (project / "memory" / "constitution.md").write_text(page, encoding="utf-8")
    return project


def _episode(
    project,
    run_id,
    summary="imported the feeds cleanly",
    task="importer",
    status="completed",
    shown=None,
):
    episodes = project / ".poieo" / "episodes"
    episodes.mkdir(parents=True, exist_ok=True)
    record = {"run_id": run_id, "task": task, "status": status, "summary": summary}
    if shown is not None:
        record["shown"] = shown
    (episodes / f"{run_id}.json").write_text(json.dumps(record), encoding="utf-8")
    return run_id


def _entry(project, slug, text):
    (project / "memory" / "facts" / f"{slug}.md").write_text(text, encoding="utf-8")


def _binding(script):
    return BindingSpec.model_validate(
        {
            "name": "test",
            "providers": {
                "fake": {"type": "mock", "options": {"responses": {"learner": script}}}
            },
            "default": {"provider": "fake", "model": "mock-model"},
        }
    )


def _proposal(entries=(), set_aside=()):
    return json.dumps({"entries": list(entries), "set_aside": list(set_aside)})


async def _learn(project, script):
    binding = _binding(script)
    async with ProviderPool(binding) as pool:
        return await learn(project, binding, pool)


def _facts(project):
    return sorted(p.name for p in (project / "memory" / "facts").glob("*.md"))


async def test_an_entry_learned_carries_the_runs_that_taught_it(tmp_path):
    project = _project(tmp_path)
    one = _episode(project, "20260824T010000-aaaaaaaa")
    _episode(project, "20260824T020000-bbbbbbbb")

    result = await _learn(
        project,
        _proposal(entries=[{"slug": "batch-cap", "body": "Batches cap at 50.", "from": [one]}]),
    )

    assert result.kept == ["batch-cap"]
    text = (project / "memory" / "facts" / "batch-cap.md").read_text(encoding="utf-8")
    assert one in text
    assert "bbbbbbbb" not in text
    assert "Batches cap at 50." in text


async def test_a_forged_from_is_cut_to_the_records_actually_shown(tmp_path):
    project = _project(tmp_path)
    one = _episode(project, "20260824T010000-aaaaaaaa")
    two = _episode(project, "20260824T020000-bbbbbbbb")

    await _learn(
        project,
        _proposal(
            entries=[{"slug": "cap", "body": "Caps hold.", "from": ["20990101T000000-ffffffff"]}]
        ),
    )

    text = (project / "memory" / "facts" / "cap.md").read_text(encoding="utf-8")
    # Nothing it named was shown, so the whole night is the source.
    assert one in text and two in text
    assert "ffffffff" not in text


async def test_a_failed_pass_rereads_and_a_passed_one_does_not(tmp_path):
    project = _project(tmp_path)
    one = _episode(project, "20260824T010000-aaaaaaaa")

    failed = await _learn(project, ["this is not json"])
    assert failed.error is not None
    assert _facts(project) == []

    passed = await _learn(
        project, [_proposal(entries=[{"slug": "cap", "body": "Caps hold.", "from": [one]}])]
    )
    assert passed.error is None and passed.read == 1

    again = await _learn(project, ["never called"])
    assert again is None  # nothing unread; no completion is even attempted


async def test_a_capped_pass_drains_across_passes_and_drops_nothing(tmp_path, monkeypatch):
    project = _project(tmp_path)
    one = _episode(project, "20260824T010000-aaaaaaaa")
    two = _episode(project, "20260824T020000-bbbbbbbb")
    monkeypatch.setattr(learning, "PASS_CAP", 1)

    first = await _learn(project, [_proposal()])
    second = await _learn(project, [_proposal()])
    third = await _learn(project, ["never called"])

    assert first.read == 1 and first.upto == one
    assert second.read == 1 and second.upto == two
    assert third is None


async def test_a_bad_slug_is_dropped_and_the_rest_still_land(tmp_path):
    project = _project(tmp_path)
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project,
        _proposal(
            entries=[
                {"slug": "../evil", "body": "Escape the folder."},
                {"slug": "fine-entry", "body": "Batches cap at 50."},
            ]
        ),
    )

    assert result.kept == ["fine-entry"]
    assert result.dropped and "../evil" in result.dropped[0]
    assert _facts(project) == ["fine-entry.md"]


async def test_a_colliding_slug_never_overwrites(tmp_path):
    project = _project(tmp_path)
    _entry(project, "batch-cap", "What a person wrote.")
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project, _proposal(entries=[{"slug": "batch-cap", "body": "Machine text."}])
    )

    assert result.kept == []
    text = (project / "memory" / "facts" / "batch-cap.md").read_text(encoding="utf-8")
    assert text == "What a person wrote."


async def test_a_dangling_link_in_a_proposal_is_dropped(tmp_path):
    project = _project(tmp_path)
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project,
        _proposal(
            entries=[
                {"slug": "leaner", "body": "Leans on air.", "links": {"depends_on": ["ghost"]}},
                {"slug": "solid", "body": "Stands alone."},
            ]
        ),
    )

    assert result.kept == ["solid"]
    assert any("ghost" in line for line in result.dropped)


async def test_a_set_aside_changes_one_line_and_keeps_the_body(tmp_path):
    project = _project(tmp_path)
    body = "Caps sat at 10 once.\nSecond line, kept byte for byte."
    _entry(project, "old-cap", f"---\nscope: [importer]\n---\n{body}")
    _entry(project, "new-cap", "Caps sit at 50 now.")
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project, _proposal(set_aside=[{"entry": "old-cap", "because": "new-cap"}])
    )

    assert result.set_aside == ["old-cap"]
    text = (project / "memory" / "facts" / "old-cap.md").read_text(encoding="utf-8")
    assert "superseded_by: new-cap" in text
    assert text.endswith(body)
    assert "scope: [importer]" in text


async def test_a_set_aside_may_point_at_an_entry_kept_this_pass(tmp_path):
    project = _project(tmp_path)
    _entry(project, "old-cap", "Caps sat at 10 once.")
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project,
        _proposal(
            entries=[{"slug": "new-cap", "body": "Caps sit at 50 now."}],
            set_aside=[{"entry": "old-cap", "because": "new-cap"}],
        ),
    )

    assert result.kept == ["new-cap"] and result.set_aside == ["old-cap"]


async def test_a_set_aside_of_a_missing_entry_is_dropped(tmp_path):
    project = _project(tmp_path)
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(project, _proposal(set_aside=[{"entry": "ghost", "because": "ghost"}]))
    assert result.set_aside == []
    assert any("ghost" in line for line in result.dropped)


async def test_an_empty_proposal_is_a_success(tmp_path):
    project = _project(tmp_path)
    one = _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(project, _proposal())
    assert result.error is None and result.upto == one and result.kept == []

    record = (project / ".poieo" / "learning.jsonl").read_text(encoding="utf-8")
    assert one in record


async def test_non_json_fails_the_pass_and_moves_nothing(tmp_path):
    project = _project(tmp_path)
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(project, "the night was uneventful, thanks")
    assert result.error is not None
    assert _facts(project) == []
    record = (project / ".poieo" / "learning.jsonl").read_text(encoding="utf-8")
    assert "uneventful" not in record  # the record says it failed, not what the model said


async def test_the_page_is_never_written(tmp_path):
    project = _project(tmp_path, page="Never push to main.")
    _episode(project, "20260824T010000-aaaaaaaa")

    await _learn(project, _proposal(entries=[{"slug": "cap", "body": "Caps hold."}]))
    page = (project / "memory" / "constitution.md").read_text(encoding="utf-8")
    assert page == "Never push to main."


async def test_a_memoryless_project_never_gains_a_folder(tmp_path):
    project = tmp_path / "tasks"
    project.mkdir()
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(project, ["never called"])
    assert result is None
    assert not (project / "memory").exists()


# -- the pass wears in what helped -------------------------------------------
#
# Three factors or nothing: cited (the entry's own words in the run's
# output), succeeded, and a declared connection between the pair.


from poieo.strength import wear_of


def _connected_pair(project):
    _entry(
        project,
        "batch-cap",
        "The importer caps batches at fifty exactly. [[retry-window]]",
    )
    _entry(project, "retry-window", "Retry refused batches after the window passes.")


CITING = "split the batches at fifty and retried after the window"


async def test_connected_cited_entries_in_a_completed_run_wear_in(tmp_path):
    project = _project(tmp_path)
    _connected_pair(project)
    _episode(
        project,
        "20260824T010000-aaaaaaaa",
        summary=CITING,
        shown=["batch-cap", "retry-window"],
    )

    await _learn(project, _proposal())
    assert wear_of(project)[frozenset(("batch-cap", "retry-window"))] > 0


async def test_shown_but_uncited_earns_nothing(tmp_path):
    project = _project(tmp_path)
    _connected_pair(project)
    _episode(
        project,
        "20260824T010000-aaaaaaaa",
        summary="nothing worth doing tonight",
        shown=["batch-cap", "retry-window"],
    )

    await _learn(project, _proposal())
    assert wear_of(project) == {}


async def test_a_failed_run_earns_nothing(tmp_path):
    project = _project(tmp_path)
    _connected_pair(project)
    _episode(
        project,
        "20260824T010000-aaaaaaaa",
        summary=CITING,
        status="failed",
        shown=["batch-cap", "retry-window"],
    )

    await _learn(project, _proposal())
    assert wear_of(project) == {}


async def test_an_unconnected_cited_pair_earns_nothing(tmp_path):
    project = _project(tmp_path)
    _entry(project, "batch-cap", "The importer caps batches at fifty exactly.")
    _entry(project, "retry-window", "Retry refused batches after the window passes.")
    _episode(
        project,
        "20260824T010000-aaaaaaaa",
        summary=CITING,
        shown=["batch-cap", "retry-window"],
    )

    await _learn(project, _proposal())
    assert wear_of(project) == {}


async def test_a_disagreeing_pair_never_wears_in(tmp_path):
    project = _project(tmp_path)
    _entry(
        project,
        "batch-cap",
        "---\nlinks:\n  contradicts: [retry-window]\n---\n"
        "The importer caps batches at fifty exactly.",
    )
    _entry(project, "retry-window", "Retry refused batches after the window passes.")
    _episode(
        project,
        "20260824T010000-aaaaaaaa",
        summary=CITING,
        shown=["batch-cap", "retry-window"],
    )

    await _learn(project, _proposal())
    assert wear_of(project) == {}


async def test_a_failed_pass_earns_nothing_and_the_reread_earns_once(tmp_path):
    project = _project(tmp_path)
    _connected_pair(project)
    _episode(
        project,
        "20260824T010000-aaaaaaaa",
        summary=CITING,
        shown=["batch-cap", "retry-window"],
    )

    await _learn(project, ["this is not json"])
    assert wear_of(project) == {}

    await _learn(project, [_proposal()])
    worn = wear_of(project)[frozenset(("batch-cap", "retry-window"))]
    assert 0.9 < worn <= 1.0


# -- the second look, and the page suggestion --------------------------------


async def test_the_pass_is_shown_what_is_doubtful(tmp_path):
    project = _project(tmp_path)
    _entry(
        project,
        "feeds-note",
        "---\nanchors: ['notebook/feeds.md']\n---\nFeeds land in one file.",
    )
    _episode(project, "20260824T010000-aaaaaaaa")

    binding = _binding(_proposal())
    async with ProviderPool(binding) as pool:
        await learn(project, binding, pool)
        prompt = pool.get("fake").calls[0].messages[0]["content"]

    assert "Worth a second look" in prompt
    assert "gone" in prompt and "feeds-note" in prompt


async def test_a_quiet_night_leaves_the_prompt_as_it_was(tmp_path):
    project = _project(tmp_path)
    _entry(project, "solid", "Stands alone, anchored to nothing.")
    _episode(project, "20260824T010000-aaaaaaaa")

    binding = _binding(_proposal())
    async with ProviderPool(binding) as pool:
        await learn(project, binding, pool)
        prompt = pool.get("fake").calls[0].messages[0]["content"]

    assert "second look" not in prompt.lower()


async def test_a_doubted_entry_can_be_set_aside_by_the_pass(tmp_path):
    project = _project(tmp_path)
    _entry(
        project,
        "feeds-note",
        "---\nanchors: ['notebook/feeds.md']\n---\nFeeds land in one file.",
    )
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project,
        _proposal(
            entries=[{"slug": "feeds-split", "body": "Feeds land one file per source now."}],
            set_aside=[{"entry": "feeds-note", "because": "feeds-split"}],
        ),
    )
    assert result.set_aside == ["feeds-note"]


async def test_a_page_suggestion_is_recorded_never_written(tmp_path):
    project = _project(tmp_path)
    _episode(project, "20260824T010000-aaaaaaaa")
    before = sorted(str(p) for p in (project / "memory").rglob("*"))

    result = await _learn(
        project,
        json.dumps(
            {"entries": [], "set_aside": [], "page": "Require ISO dates in the notebook."}
        ),
    )

    assert result.page == "Require ISO dates in the notebook."
    record = (project / ".poieo" / "learning.jsonl").read_text(encoding="utf-8")
    assert "Require ISO dates" in record
    assert sorted(str(p) for p in (project / "memory").rglob("*")) == before
    assert (
        (project / "memory" / "constitution.md").read_text(encoding="utf-8")
        == "Never push to main."
    )


# -- the attic ---------------------------------------------------------------


def _aged(path, days):
    import os
    import time

    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp))


def _old_aside(project, slug="old-cap", because="new-cap", days=120):
    _entry(project, because, "Caps sit at 50 now.")
    _entry(project, slug, f"---\nsuperseded_by: {because}\n---\nCaps sat at 10 once.")
    _aged(project / "memory" / "facts" / f"{slug}.md", days)


async def test_an_old_unreferenced_set_aside_moves_to_the_attic_whole(tmp_path):
    project = _project(tmp_path)
    _old_aside(project)
    _episode(project, "20260824T010000-aaaaaaaa")

    await _learn(project, _proposal())
    assert not (project / "memory" / "facts" / "old-cap.md").exists()
    moved = (project / "memory" / "attic" / "old-cap.md").read_text(encoding="utf-8")
    assert moved == "---\nsuperseded_by: new-cap\n---\nCaps sat at 10 once."


async def test_a_referenced_set_aside_stays_however_old(tmp_path):
    project = _project(tmp_path)
    _old_aside(project)
    _entry(
        project,
        "leaner",
        "---\nlinks:\n  depends_on: [old-cap]\n---\nStill leans on the old cap.",
    )
    _episode(project, "20260824T010000-aaaaaaaa")

    await _learn(project, _proposal())
    assert (project / "memory" / "facts" / "old-cap.md").exists()


async def test_a_fresh_set_aside_stays(tmp_path):
    project = _project(tmp_path)
    _old_aside(project, days=5)
    _episode(project, "20260824T010000-aaaaaaaa")

    await _learn(project, _proposal())
    assert (project / "memory" / "facts" / "old-cap.md").exists()


async def test_attic_entries_reach_no_load_no_report_no_prompt(tmp_path):
    from poieo.memory import load_facts, memory_report, read_memory

    project = _project(tmp_path)
    _old_aside(project)
    _episode(project, "20260824T010000-aaaaaaaa")
    await _learn(project, _proposal())

    assert "old-cap" not in {fact.slug for fact in load_facts(project)}
    assert memory_report(project)["set_aside"] == 0
    block = read_memory(project) or ""
    assert "sat at 10" not in block


async def test_an_attic_collision_is_skipped_and_said(tmp_path, caplog):
    project = _project(tmp_path)
    _old_aside(project)
    attic = project / "memory" / "attic"
    attic.mkdir()
    (attic / "old-cap.md").write_text("already here", encoding="utf-8")
    _episode(project, "20260824T010000-aaaaaaaa")

    with caplog.at_level("WARNING", logger="poieo.learn"):
        await _learn(project, _proposal())

    assert (project / "memory" / "facts" / "old-cap.md").exists()
    assert (attic / "old-cap.md").read_text(encoding="utf-8") == "already here"
    assert any("attic" in message for message in caplog.messages)


# -- sealing -----------------------------------------------------------------


async def test_a_file_anchor_is_sealed_when_the_pass_writes(tmp_path):
    from poieo.blob import digest, kept

    project = _project(tmp_path)
    notebook = project / "notebook"
    notebook.mkdir()
    (notebook / "feeds.md").write_text("# feeds\n- a\n- b\n", encoding="utf-8")
    _episode(project, "20260824T010000-aaaaaaaa")

    await _learn(
        project,
        _proposal(
            entries=[
                {
                    "slug": "feeds-note",
                    "body": "Feeds land in one file.",
                    "anchors": ["notebook/feeds.md"],
                }
            ]
        ),
    )

    text = (project / "memory" / "facts" / "feeds-note.md").read_text(encoding="utf-8")
    name = digest(notebook / "feeds.md")
    assert f'"notebook/feeds.md": "{name}"' in text
    assert kept(project, name).read_text(encoding="utf-8") == "# feeds\n- a\n- b\n"


async def test_a_directory_anchor_is_not_sealed_and_the_entry_lands(tmp_path):
    project = _project(tmp_path)
    (project / "notebook").mkdir()
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project,
        _proposal(
            entries=[
                {"slug": "place-note", "body": "Work lands here.", "anchors": ["notebook"]}
            ]
        ),
    )

    assert result.kept == ["place-note"]
    text = (project / "memory" / "facts" / "place-note.md").read_text(encoding="utf-8")
    assert "sealed" not in text


async def test_an_over_cap_anchor_is_skipped_and_noted(tmp_path, monkeypatch):
    import poieo.blob as blob

    monkeypatch.setattr(blob, "KEEP_CAP", 10)
    project = _project(tmp_path)
    notebook = project / "notebook"
    notebook.mkdir()
    (notebook / "fat.bin").write_bytes(b"x" * 100)
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project,
        _proposal(
            entries=[
                {"slug": "fat-note", "body": "The big file matters.", "anchors": ["notebook/fat.bin"]}
            ]
        ),
    )

    assert result.kept == ["fat-note"]
    text = (project / "memory" / "facts" / "fat-note.md").read_text(encoding="utf-8")
    assert "sealed" not in text
    assert any("fat.bin" in note for note in result.dropped)


# -- letting go --------------------------------------------------------------


def _stale_blob(project, content=b"old bytes"):
    import hashlib

    store = project / ".poieo" / "blobs"
    store.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(content).hexdigest()
    (store / name).write_bytes(content)
    _aged(store / name, 120)
    return name


async def test_an_old_unreferenced_keepsake_is_let_go_and_listed(tmp_path):
    project = _project(tmp_path)
    name = _stale_blob(project)
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(project, _proposal())
    assert result.let_go == [name]
    assert not (project / ".poieo" / "blobs" / name).exists()


async def test_a_keepsake_referenced_from_the_attic_survives(tmp_path):
    project = _project(tmp_path)
    name = _stale_blob(project)
    attic = project / "memory" / "attic"
    attic.mkdir()
    (attic / "old-note.md").write_text(
        "---\nanchors: ['notebook/feeds.md']\nsuperseded_by: old-note\n"
        f'sealed: {{"notebook/feeds.md": "{name}"}}\n---\nOnce true.',
        encoding="utf-8",
    )
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(project, _proposal())
    assert result.let_go == []
    assert (project / ".poieo" / "blobs" / name).exists()


async def test_a_fresh_keepsake_survives(tmp_path):
    import hashlib

    project = _project(tmp_path)
    store = project / ".poieo" / "blobs"
    store.mkdir(parents=True)
    name = hashlib.sha256(b"fresh bytes").hexdigest()
    (store / name).write_bytes(b"fresh bytes")
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(project, _proposal())
    assert result.let_go == []
    assert (store / name).exists()


# -- hardening ---------------------------------------------------------------


async def test_a_record_without_a_run_id_cannot_jam_the_bookmark(tmp_path):
    project = _project(tmp_path)
    episodes = project / ".poieo" / "episodes"
    episodes.mkdir(parents=True)
    (episodes / "20260824T010000-aaaaaaaa.json").write_text(
        json.dumps({"task": "importer", "status": "completed", "summary": "quiet"}),
        encoding="utf-8",
    )

    passed = await _learn(project, [_proposal()])
    assert passed.error is None and passed.upto == "20260824T010000-aaaaaaaa"

    again = await _learn(project, ["never called"])
    assert again is None  # read once, never reread


async def test_the_same_entry_cannot_be_set_aside_twice_in_one_answer(tmp_path):
    project = _project(tmp_path)
    _entry(project, "old-cap", "Caps sat at 10 once.")
    _entry(project, "new-cap", "Caps sit at 50 now.")
    _entry(project, "other-cap", "Caps sit at 60 elsewhere.")
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project,
        _proposal(
            set_aside=[
                {"entry": "old-cap", "because": "new-cap"},
                {"entry": "old-cap", "because": "other-cap"},
            ]
        ),
    )

    assert result.set_aside == ["old-cap"]
    text = (project / "memory" / "facts" / "old-cap.md").read_text(encoding="utf-8")
    assert "superseded_by: new-cap" in text and "other-cap" not in text
    assert any("already set aside" in line for line in result.dropped)


async def test_two_entries_cannot_set_each_other_aside(tmp_path):
    project = _project(tmp_path)
    _entry(project, "cap-a", "Caps sit at 50, says a.")
    _entry(project, "cap-b", "Caps sit at 60, says b.")
    _episode(project, "20260824T010000-aaaaaaaa")

    result = await _learn(
        project,
        _proposal(
            set_aside=[
                {"entry": "cap-a", "because": "cap-b"},
                {"entry": "cap-b", "because": "cap-a"},
            ]
        ),
    )

    # The first aside stands; the second would lean the memory on nothing.
    assert result.set_aside == ["cap-a"]
    text = (project / "memory" / "facts" / "cap-b.md").read_text(encoding="utf-8")
    assert "superseded_by" not in text
