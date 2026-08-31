"""What a task is shown is chosen by what it is and where it works.

The index is derived and disposable -- delete it and nothing changes but
speed -- and the plain scan behind the same interface must return the same
entries, or the fallback is a different feature wearing the same name.
"""

import pytest
from conftest import at, remember
from test_card import write_card

import poieo.memory.index as memory_index
import poieo.memory.recall as memory_recall
from poieo.card import load_card
from poieo.memory import read_memory, start_memory, write_page


def _project(tmp_path, prompt="review the api batch sizes in the importer"):
    """A card, its folder, and a memory folder beside it."""
    path = write_card(tmp_path, "importer", f"name: mind the importer\nprompt: {prompt}\n")
    start_memory(tmp_path / "tasks")
    return load_card(path), tmp_path / "tasks"


def _entry_for(tmp_path):
    _, project = _project(tmp_path)
    return _fact(project, "refusals", "A refused feed is noted, never retried.")


def _fact(project, slug, body, matter=""):
    return remember(project, slug, f"---\n{matter}\n---\n{body}" if matter else body)


def test_the_entry_a_task_matches_comes_first(tmp_path):
    """Matching still decides the *order*. It no longer decides who is in the
    room: an entry the task shares no word with used to be dropped, and the
    space it would have taken went unused."""
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")
    _fact(project, "unrelated", "The deploy pipeline reruns twice on Mondays.")

    block = read_memory(project, task)
    assert "What earlier work here has learned:" in block
    assert block.index("batch sizes over 50") < block.index("deploy pipeline")


def test_room_left_over_goes_to_entries_the_task_matches_nothing_in(tmp_path):
    """The budget is what says no. Below it, an entry in scope is shown --
    dropping one to leave the room empty helps nobody."""
    task, project = _project(tmp_path)
    _fact(project, "unrelated", "The deploy pipeline reruns twice on Mondays.")

    assert "deploy pipeline" in (read_memory(project, task) or "")


def test_a_full_budget_still_keeps_the_matched_ones(tmp_path, monkeypatch):
    """When there is not room for everyone, matching decides who is cut."""
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")
    for i in range(6):
        _fact(project, f"filler-{i}", f"Something unrelated to anything, number {i}.")

    monkeypatch.setattr(memory_recall, "ENTRIES_BUDGET", 80)
    block = read_memory(project, task)
    assert "batch sizes over 50" in block


def test_room_is_counted_in_what_this_task_could_be_shown(tmp_path):
    """Filling stops when the *task's* room is full, not when enough rows have
    been read. Counting raw rows would stop at a run of entries scoped to other
    cards and leave this one's room empty anyway."""
    task, project = _project(tmp_path)
    _fact(project, "mine", "Nothing here is about anything the card mentions.")
    for i in range(8):
        _fact(project, f"theirs-{i}", f"Belongs to the exporter, number {i}.", "scope: [exporter]")

    assert "Nothing here is about anything" in (read_memory(project, task) or "")


def test_two_entries_disputing_each_other_do_not_both_arrive(tmp_path):
    """The veto holds between entries that arrive together, not only between one
    already shown and one about to be. Otherwise a pair would slip in as a pair.
    """
    task, project = _project(tmp_path)
    _fact(project, "wild-claim", "Nothing ever gets refused, honestly.")
    _fact(
        project,
        "measured",
        "Refusals happen most nights.",
        matter="links:\n  contradicts: [wild-claim]",
    )

    block = read_memory(project, task) or ""
    assert ("honestly" in block) != ("most nights" in block)


def test_an_entry_outside_this_task_is_still_never_shown(tmp_path):
    """Filling the room is not the same as ignoring scope. Scope is the
    author saying who an entry is for, and that still holds."""
    task, project = _project(tmp_path)
    _fact(project, "for-another", "The exporter api needs batch flushing.", "scope: [exporter]")

    assert read_memory(project, task) is None


def test_the_fallback_returns_the_same_entries_as_fts(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")
    _fact(project, "retries", "The importer retries three times before giving up.")
    _fact(project, "unrelated", "The deploy pipeline reruns twice on Mondays.")

    preferred = read_memory(project, task)
    monkeypatch.setattr(memory_index, "fts_available", lambda: False)
    assert read_memory(project, task) == preferred


def test_a_plural_and_its_singular_are_the_same_word(tmp_path):
    """The failure this was written for, reproduced against a real model: a card
    whose prompt says "feeds" never saw an entry that says "feed". Matching the
    letters exactly is what buried it, and the damage doubled -- an entry never
    shown is then counted as one that was shown and never used."""
    task, project = _project(tmp_path, prompt="pull the feeds into the notebook")
    _fact(project, "one-at-a-time", "The mock feed answers everything; batches of one are wasted turns.")

    block = read_memory(project, task)
    assert "batches of one are wasted turns" in block


def test_a_word_shape_counts_the_same_for_both_judges(tmp_path):
    """`words()` is shared on purpose -- what a card is shown and whether an
    entry did real work must not disagree about what an entry says. Loosening
    one side alone would be how they start to."""
    from poieo.memory import used_in
    from poieo.memory.entries import words

    assert words("the feeds were refused") == words("a feed was refused")
    entry = _entry_for(tmp_path)
    assert used_in(entry, {"summary": "a refused feed, noted", "outputs": {}})


def test_the_shape_holds_whichever_side_is_plural(tmp_path, monkeypatch):
    """Shaping the words a card asks with, but storing the words an entry was
    written with, would only match in one direction -- and would make the
    lookup disagree with the scoring that follows it, which is the one thing
    the two paths must never do."""
    task, project = _project(tmp_path, prompt="pull the feed into the notebook")
    _fact(project, "many", "Refusing feeds are noted, never retried.")

    block = read_memory(project, task)
    assert "Refusing feeds are noted" in block
    # And with no lookup to narrow with, the same entry and no other.
    monkeypatch.setattr(memory_index, "fts_available", lambda: False)
    assert read_memory(project, task) == block


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
    monkeypatch.setattr(memory_recall, "ENTRIES_BUDGET", 40)
    block = read_memory(project, task)
    assert "Watch the api batch limit here." in block
    assert "Another note" not in block


def test_an_anchored_entry_arrives_even_without_a_shared_word(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "quirk", "Symlinks misbehave under WSL mounts.", "anchors: ['../project']")

    block = read_memory(project, task)
    assert "Symlinks misbehave" in block
    # And the slower lookup agrees, or it is a different feature.
    monkeypatch.setattr(memory_index, "fts_available", lambda: False)
    assert read_memory(project, task) == block


def test_the_budget_cuts_whole_entries_and_spares_the_page(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    page = "Never push to main.\n" + "x" * 300
    write_page(project, page)
    _fact(project, "one", "The api batch importer note number one.")
    _fact(project, "two", "The api batch importer note number two.")

    monkeypatch.setattr(memory_recall, "ENTRIES_BUDGET", 45)
    block = read_memory(project, task)
    # The page arrives whole however small the budget for learned entries is.
    assert page.strip() in block
    # One whole entry fits; the other is left out entirely, never half-shown.
    assert block.count("note number") == 1
    assert "number one." in block or "number two." in block


def test_one_oversized_entry_loses_only_its_own_place(tmp_path, monkeypatch):
    """Nothing caps how long an entry may be, so one too big for the budget is
    a thing that happens. It must cost itself its place and nobody else theirs
    -- stopping at it hid every entry ranked below it, silently."""
    task, project = _project(tmp_path)
    _fact(project, "aaa-huge", "The api batch importer " + "x" * 5000)
    _fact(project, "bbb-small", "The api batch importer note that still fits.")

    block = read_memory(project, task)
    assert "note that still fits." in block


def test_a_dropped_lookup_is_rebuilt_silently(tmp_path):
    """The lookup is derived, still: drop the table and the next read builds
    it again, having lost nothing but the time to do so."""
    import sqlite3

    if not memory_index.fts_available():
        pytest.skip("this Python build has no FTS5, so there is no lookup table")
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")
    first = read_memory(project, task)

    con = sqlite3.connect(at(project).longterm())
    con.executescript("DROP TABLE pieces_fts; DROP TRIGGER pieces_after_insert;")
    con.commit()
    con.close()

    assert read_memory(project, task) == first


# -- following what entries name ---------------------------------------------
#
# Direct evidence before association: a neighbor's claim to the prompt is
# its seed's, so no neighbor ever outranks a direct hit, escapes scope,
# resurrects a set-aside entry, or brings neighbors of its own.


def test_a_mentioned_entry_joins_despite_sharing_no_word(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[folder-layout]]")
    _fact(project, "folder-layout", "Feeds land alphabetically, newest last.")

    block = read_memory(project, task)
    assert "over 50." in block
    assert "alphabetically" in block
    assert block.index("over 50.") < block.index("alphabetically")


def test_a_mention_is_followed_in_both_directions(tmp_path):
    # The mentioning entry shares no word with the task -- not even through
    # the mention text itself -- so only reverse-following can bring it.
    task, project = _project(tmp_path)
    _fact(project, "cap-fifty", "The api rejects batch sizes over 50.")
    _fact(project, "quiet-note", "Feeds land alphabetically. See [[cap-fifty]].")

    assert "alphabetically" in read_memory(project, task)


def test_a_leaned_on_entry_joins_forward_only(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(
        project,
        "batch-cap",
        "The api rejects batch sizes over 50.",
        matter="links:\n  depends_on: [quiet-note]",
    )
    _fact(project, "quiet-note", "Feeds land alphabetically, newest last.")
    _fact(
        project,
        "orphan",
        "Nothing links back here tonight.",
        matter="links:\n  depends_on: [batch-cap]",
    )

    # Association reach is what is under test, so the room is closed to the
    # width of what association should bring: with space left over an entry
    # arrives on its own, which would hide whether the walk reached it.
    monkeypatch.setattr(memory_recall, "ENTRIES_BUDGET", 80)
    block = read_memory(project, task)
    assert "alphabetically" in block
    assert "links back here" not in block


def test_a_disagreeing_entry_is_never_dragged_in(tmp_path):
    task, project = _project(tmp_path)
    _fact(
        project,
        "batch-cap",
        "The api rejects batch sizes over 50.",
        matter="links:\n  contradicts: [wild-claim]",
    )
    _fact(project, "wild-claim", "Nothing ever gets refused, honestly.")

    assert "honestly" not in read_memory(project, task)


def test_neighbors_come_after_every_direct_hit(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[folder-layout]]")
    _fact(project, "retry-note", "The importer retries the api batch once.")
    _fact(project, "folder-layout", "Feeds land alphabetically, newest last.")

    block = read_memory(project, task)
    assert block.index("retries") < block.index("alphabetically")


def test_a_neighbor_out_of_scope_stays_out(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[exporter-note]]")
    _fact(project, "exporter-note", "Digest pages flush nightly.", matter="scope: [exporter]")

    assert "flush nightly" not in read_memory(project, task)


def test_a_set_aside_neighbor_stays_out(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[old-cap]]")
    _fact(project, "old-cap", "Caps sat lower once.", matter="superseded_by: batch-cap")

    assert "sat lower" not in read_memory(project, task)


def test_one_hop_means_one_hop(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[near]]")
    _fact(project, "near", "Feeds land alphabetically. [[far]]")
    _fact(project, "far", "Somewhere a bell rings twice.")

    # Association reach is what is under test, so the room is closed to the
    # width of what association should bring: with space left over an entry
    # arrives on its own, which would hide whether the walk reached it.
    monkeypatch.setattr(memory_recall, "ENTRIES_BUDGET", 80)
    block = read_memory(project, task)
    assert "alphabetically" in block
    assert "bell rings" not in block


def test_the_budget_still_cuts_whole_entries_across_neighbors(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[folder-layout]]")
    _fact(project, "folder-layout", "Feeds land alphabetically, newest last.")

    monkeypatch.setattr(memory_recall, "ENTRIES_BUDGET", 60)
    block = read_memory(project, task)
    assert "over 50." in block
    assert "alphabetically" not in block


def test_the_fallback_still_returns_the_same_entries(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[folder-layout]]")
    _fact(project, "folder-layout", "Feeds land alphabetically, newest last.")
    _fact(project, "quiet-note", "Digest ordering held steady. [[batch-cap]]")

    preferred = read_memory(project, task)
    monkeypatch.setattr(memory_index, "fts_available", lambda: False)
    assert read_memory(project, task) == preferred


# -- strength paths --------------------------------------------------------------
#
# Wear reorders neighbors and extends reach one strength hop; it never outranks
# direct evidence, crosses a filter, or diverges the two lookup backends.
# With nothing reinforced, everything above this line is the whole behavior.


def _worn(project, a, b, times=1):
    from poieo.strength import reinforce

    for _ in range(times):
        reinforce(project, [(a, b)])


def test_a_worn_neighbor_outranks_its_unworn_sibling(tmp_path):
    task, project = _project(tmp_path)
    _fact(
        project,
        "batch-cap",
        "The api rejects batch sizes over 50. [[alpha-note]] [[zeta-note]]",
    )
    _fact(project, "alpha-note", "Feeds land alphabetically, newest last.")
    _fact(project, "zeta-note", "Zebra ordering holds on holidays.")
    _worn(project, "batch-cap", "zeta-note")

    block = read_memory(project, task)
    assert block.index("Zebra ordering") < block.index("alphabetically")


def test_an_empty_strength_store_changes_nothing(tmp_path):
    task, project = _project(tmp_path)
    _fact(
        project,
        "batch-cap",
        "The api rejects batch sizes over 50. [[alpha-note]] [[zeta-note]]",
    )
    _fact(project, "alpha-note", "Feeds land alphabetically, newest last.")
    _fact(project, "zeta-note", "Zebra ordering holds on holidays.")

    block = read_memory(project, task)
    assert block.index("alphabetically") < block.index("Zebra ordering")


def test_a_worn_two_hop_path_arrives(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[near]]")
    _fact(project, "near", "Feeds land alphabetically. [[far]]")
    _fact(project, "far", "Somewhere a bell rings twice.")
    _worn(project, "near", "far")

    block = read_memory(project, task)
    assert "bell rings" in block
    assert block.index("alphabetically") < block.index("bell rings")


def test_an_unworn_second_hop_is_never_taken(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[near]]")
    _fact(project, "near", "Feeds land alphabetically. [[far]]")
    _fact(project, "far", "Somewhere a bell rings twice.")
    _worn(project, "batch-cap", "near")  # the first hop is strength; the second is not

    # Association reach is what is under test, so the room is closed to the
    # width of what association should bring: with space left over an entry
    # arrives on its own, which would hide whether the walk reached it.
    monkeypatch.setattr(memory_recall, "ENTRIES_BUDGET", 80)
    assert "bell rings" not in read_memory(project, task)


def test_no_neighbor_outranks_a_direct_hit_however_worn(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[quiet-note]]")
    _fact(project, "retry-note", "The importer retries the api batch once.")
    _fact(project, "quiet-note", "Feeds land alphabetically, newest last.")
    _worn(project, "batch-cap", "quiet-note", times=12)

    block = read_memory(project, task)
    assert block.index("retries") < block.index("alphabetically")


def test_a_worn_path_never_crosses_scope_or_resurrects_the_set_aside(tmp_path):
    task, project = _project(tmp_path)
    _fact(
        project,
        "batch-cap",
        "The api rejects batch sizes over 50. [[exporter-note]] [[old-cap]]",
    )
    _fact(project, "exporter-note", "Digest pages flush nightly.", matter="scope: [exporter]")
    _fact(project, "old-cap", "Caps sat lower once.", matter="superseded_by: batch-cap")
    _worn(project, "batch-cap", "exporter-note", times=5)
    _worn(project, "batch-cap", "old-cap", times=5)

    block = read_memory(project, task)
    assert "flush nightly" not in block
    assert "sat lower" not in block


def test_the_scan_and_the_index_still_agree_on_worn_paths(tmp_path, monkeypatch):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[near]]")
    _fact(project, "near", "Feeds land alphabetically. [[far]]")
    _fact(project, "far", "Somewhere a bell rings twice.")
    _worn(project, "near", "far")

    preferred = read_memory(project, task)
    monkeypatch.setattr(memory_index, "fts_available", lambda: False)
    assert read_memory(project, task) == preferred


def test_nothing_is_ever_written_inside_the_audited_layer(tmp_path):
    """Reading builds an index, and the index lives in `memory/cache/` --
    inside `memory/`, one folder over. So the guarantee is not "nothing is
    written under memory/" but the one that matters: the entries a person
    wrote and reads are never touched by the machinery that reads them."""
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")
    before = sorted(p.name for p in at(project).longterm().rglob("*"))

    read_memory(project, task)
    after = sorted(p.name for p in at(project).longterm().rglob("*"))
    assert after == before


def test_a_mention_does_not_outvote_a_disagreement(tmp_path):
    # "this disputes [[wild-claim]]" is an ordinary way to write a
    # disagreement -- the mention must not smuggle the disputed entry in.
    task, project = _project(tmp_path)
    _fact(
        project,
        "batch-cap",
        "The api rejects batch sizes over 50, whatever [[wild-claim]] says.",
        matter="links:\n  contradicts: [wild-claim]",
    )
    _fact(project, "wild-claim", "Nothing ever gets refused, honestly.")

    assert "honestly" not in read_memory(project, task)
