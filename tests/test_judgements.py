"""A verdict a learning pass left for a card -- which of the entries it would
be shown actually apply -- is read at recall for free, and only while the card
and the candidate set are the ones it was given."""

import json

from conftest import remember
from test_card import write_card
from test_learn import _binding

from poieo.card import load_card
from poieo.learn import refresh_judgements
from poieo.memory import judge_candidates, judgement_is_stale, read_memory, remember_judgement, start_memory
from poieo.providers import ProviderPool


def _project(tmp_path, prompt="rotate the nginx logs older than a week"):
    path = write_card(tmp_path, "rotate", f"name: rotate the logs\nprompt: {prompt}\n")
    start_memory(tmp_path / "tasks")
    return load_card(path), tmp_path / "tasks"


def _lessons(project):
    remember(project, "nginx", "Nginx logs must be rotated with copytruncate; a move leaves the handle open.")
    # The look-alike: same words, a neighbouring system, the opposite advice.
    remember(project, "app-logs", "Application logs must be rotated by move-and-signal, never copytruncate.")


def test_a_verdict_drops_what_the_judge_rejected_and_keeps_the_rest(tmp_path):
    task, project = _project(tmp_path)
    _lessons(project)
    before = read_memory(project, task) or ""
    assert "copytruncate; a move" in before and "move-and-signal" in before

    remember_judgement(project, task, judge_candidates(project, task), keep=["nginx"])

    after = read_memory(project, task) or ""
    assert "copytruncate; a move" in after
    assert "move-and-signal" not in after


def test_a_verdict_for_other_candidates_or_other_card_text_is_ignored(tmp_path):
    """A memory that has learned since, or a card edited since, is shown as it
    always was until the next pass judges it again. Nothing waits."""
    task, project = _project(tmp_path)
    _lessons(project)
    remember_judgement(project, task, judge_candidates(project, task), keep=["nginx"])

    remember(project, "newer", "Compress rotated logs a week later, not the same night.")
    assert judgement_is_stale(project, task, judge_candidates(project, task))
    assert "move-and-signal" in (read_memory(project, task) or "")

    edited, _ = _project(tmp_path, prompt="rotate and compress the nginx logs")
    assert "move-and-signal" in (read_memory(project, edited) or "")


async def test_the_pass_judges_stale_cards_only_and_keys_the_verdict_to_its_candidates(tmp_path):
    task, project = _project(tmp_path)
    _lessons(project)

    binding = _binding([json.dumps({"1": [1]})])  # the first candidate applies; the second does not
    async with ProviderPool(binding) as pool:
        assert await refresh_judgements(project, [task], binding, pool) == ["rotate"]
    block = read_memory(project, task) or ""
    assert "copytruncate; a move" in block and "move-and-signal" not in block

    binding = _binding(["never called"])
    async with ProviderPool(binding) as pool:
        assert await refresh_judgements(project, [task], binding, pool) == []


async def test_a_pass_that_cannot_answer_leaves_the_block_as_it_was(tmp_path):
    task, project = _project(tmp_path)
    _lessons(project)
    binding = _binding(["this is not json"])
    async with ProviderPool(binding) as pool:
        assert await refresh_judgements(project, [task], binding, pool) == []
    assert "move-and-signal" in (read_memory(project, task) or "")


async def test_a_judge_that_keeps_nothing_is_not_believed(tmp_path):
    """Forgetting optional context is preferable to losing the work, but a
    verdict that empties the block is more likely a misread than a finding:
    it is dropped, and the card is judged again next pass."""
    task, project = _project(tmp_path)
    _lessons(project)
    binding = _binding([json.dumps({"1": []})])
    async with ProviderPool(binding) as pool:
        assert await refresh_judgements(project, [task], binding, pool) == []
    assert "copytruncate; a move" in (read_memory(project, task) or "")
