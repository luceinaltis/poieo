"""What a task is shown is chosen by what it is and where it works.

The index is derived and disposable -- delete it and nothing changes but
speed -- and the plain scan behind the same interface must return the same
entries, or the fallback is a different feature wearing the same name.
"""

from conftest import at
import pytest

import poieo.memory.index as memory_index
import poieo.memory.recall as memory_recall
from poieo.memory import read_memory
from poieo.task import load_task

from test_task import write_task


def _project(tmp_path, prompt="review the api batch sizes in the importer"):
    """A card, its folder, and a memory folder beside it."""
    path = write_task(tmp_path, "importer", f"name: mind the importer\nprompt: {prompt}\n")
    at(tmp_path / "tasks").facts().mkdir(parents=True)
    return load_task(path), tmp_path / "tasks"


def _fact(project, slug, body, matter=""):
    text = f"---\n{matter}\n---\n{body}\n" if matter else f"{body}\n"
    (at(project).facts() / f"{slug}.md").write_text(text, encoding="utf-8")


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
    monkeypatch.setattr(memory_index, "fts_available", lambda: False)
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
    at(project).constitution().write_text(page, encoding="utf-8")
    _fact(project, "one", "The api batch importer note number one.")
    _fact(project, "two", "The api batch importer note number two.")

    monkeypatch.setattr(memory_recall, "ENTRIES_BUDGET", 45)
    block = read_memory(project, task)
    # The page arrives whole however small the budget for learned entries is.
    assert page.strip() in block
    # One whole entry fits; the other is left out entirely, never half-shown.
    assert block.count("note number") == 1
    assert "number one." in block or "number two." in block


def test_a_deleted_index_is_rebuilt_silently(tmp_path):
    if not memory_index.fts_available():
        pytest.skip("this Python build has no FTS5, so there is no index file")
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50.")

    first = read_memory(project, task)
    index = at(project).index()
    assert index.is_file()

    index.unlink()
    assert read_memory(project, task) == first
    assert index.is_file()


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


def test_a_leaned_on_entry_joins_forward_only(tmp_path):
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


def test_one_hop_means_one_hop(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[near]]")
    _fact(project, "near", "Feeds land alphabetically. [[far]]")
    _fact(project, "far", "Somewhere a bell rings twice.")

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


def test_an_unworn_second_hop_is_never_taken(tmp_path):
    task, project = _project(tmp_path)
    _fact(project, "batch-cap", "The api rejects batch sizes over 50. [[near]]")
    _fact(project, "near", "Feeds land alphabetically. [[far]]")
    _fact(project, "far", "Somewhere a bell rings twice.")
    _worn(project, "batch-cap", "near")  # the first hop is strength; the second is not

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
