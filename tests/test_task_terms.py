"""What else a task could be called widens what recall asks with -- only while
the card still reads as it did when those words were written, and written by a
pass a person never has to wait for."""

import json

from conftest import remember
from test_card import write_card
from test_learn import _binding

from poieo.card import load_card
from poieo.learn import refresh_task_terms
from poieo.memory import read_memory, start_memory, task_terms
from poieo.memory.task_terms import remember as remember_task_terms
from poieo.memory.task_terms import stale
from poieo.providers import ProviderPool


def _project(tmp_path, prompt="review the api batch sizes in the importer"):
    path = write_card(tmp_path, "importer", f"name: mind the importer\nprompt: {prompt}\n")
    start_memory(tmp_path / "tasks")
    return load_card(path), tmp_path / "tasks"


def _crowd(project):
    # Every neighbour shares a word with the card on its own, so the lesson
    # under test is behind all of them unless something lifts it.
    for i in range(6):
        remember(project, f"about-{i}", f"Note {i} about the api batch queue.")


def test_a_cards_terms_lift_a_lesson_worded_in_other_words(tmp_path):
    task, project = _project(tmp_path)
    remember(project, "descriptor", "The web server keeps its descriptor after a rename; truncate in place.")
    _crowd(project)
    assert "keeps its descriptor" not in (read_memory(project, task) or "").split("Note 0")[0]

    remember_task_terms(project, task, "web server descriptor rename truncate")

    block = read_memory(project, task) or ""
    assert block.index("keeps its descriptor") < block.index("Note 0")


def test_terms_written_for_other_card_text_are_ignored(tmp_path):
    """A person edits a prompt because they did not like it. Terms written for
    the old wording must not steer the new one: they are skipped, which is
    today's behaviour, until a pass writes fresh ones."""
    task, project = _project(tmp_path)
    remember(project, "descriptor", "The web server keeps its descriptor after a rename; truncate in place.")
    _crowd(project)
    remember_task_terms(project, task, "web server descriptor rename truncate")

    edited, _ = _project(tmp_path, prompt="review the api batch sizes and the retry policy in the importer")

    assert task_terms(project, edited) == ""
    block = read_memory(project, edited) or ""
    assert block.index("Note 0") < block.index("keeps its descriptor")


async def test_the_pass_writes_terms_for_stale_cards_only_and_stamps_them(tmp_path):
    task, project = _project(tmp_path)
    other = load_card(write_card(tmp_path, "exporter", "name: publish the digest\nprompt: publish what is new\n"))
    remember_task_terms(project, other, "digest newsletter roundup")  # already fresh

    assert [c.slug for c in stale(project, [task, other])] == ["importer"]

    binding = _binding([json.dumps({"1": "importer feeds ingest batches upload"})])
    async with ProviderPool(binding) as pool:
        written = await refresh_task_terms(project, [task, other], binding, pool)
    assert written == ["importer"]
    assert task_terms(project, task) == "importer feeds ingest batches upload"
    assert task_terms(project, other) == "digest newsletter roundup"

    # Nothing stale, nothing asked: the script would fail the test if reached.
    binding = _binding(["never called"])
    async with ProviderPool(binding) as pool:
        assert await refresh_task_terms(project, [task, other], binding, pool) == []


async def test_a_pass_that_cannot_answer_leaves_the_cards_bare_and_says_so(tmp_path):
    task, project = _project(tmp_path)
    binding = _binding(["this is not json"])
    async with ProviderPool(binding) as pool:
        assert await refresh_task_terms(project, [task], binding, pool) == []
    assert task_terms(project, task) == ""
