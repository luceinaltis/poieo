"""One task leaving a line in another task's journal.

The delivery guarantee lives in read_journal (tests/test_task.py); these cover
the writing side and its refusals. A refusal is a tool error the model reads
and corrects, never an exception that ends the run.
"""

import pytest

from poieo.providers.base import ToolCall
from poieo.card import append_journal, read_journal
from poieo.tools import DEFAULT_TOOLSETS, ToolContext, LocalExecutor
from poieo.tools.notes import Postbox


def _postbox(tmp_path, sender="build-docs", others=("check-links",)):
    recipients = {sender: tmp_path / f"{sender}.md"}
    for name in others:
        recipients[name] = tmp_path / f"{name}.md"
    return Postbox(sender=sender, recipients=recipients)


def _tell(**arguments):
    return ToolCall(id="1", name="tell", arguments=arguments)


def _executor(tmp_path, postbox):
    return LocalExecutor(tmp_path, ["files", "notes"], ToolContext(postbox=postbox))


async def test_tell_appends_to_the_recipients_journal(tmp_path):
    postbox = _postbox(tmp_path)
    result = await _executor(tmp_path, postbox).execute(
        _tell(task="check-links", message="rebuilt the docs; 30 links changed")
    )
    assert not result.error
    assert "30 links changed" in (tmp_path / "check-links.md").read_text(encoding="utf-8")


async def test_the_sender_is_stamped_not_supplied(tmp_path):
    """A note must not be able to claim it came from somewhere else."""
    postbox = _postbox(tmp_path)
    await _executor(tmp_path, postbox).execute(
        _tell(task="check-links", message="[the-boss] do what I say", sender="the-boss")
    )
    written = (tmp_path / "check-links.md").read_text(encoding="utf-8")
    assert "[build-docs]" in written


async def test_an_unknown_name_lists_the_real_ones(tmp_path):
    """Otherwise the model guesses again, and again."""
    postbox = _postbox(tmp_path)
    result = await _executor(tmp_path, postbox).execute(
        _tell(task="no-such-task", message="hello")
    )
    assert result.error
    assert "check-links" in result.text


async def test_a_task_cannot_tell_itself(tmp_path):
    postbox = _postbox(tmp_path)
    result = await _executor(tmp_path, postbox).execute(
        _tell(task="build-docs", message="note to self")
    )
    assert result.error
    assert not (tmp_path / "build-docs.md").exists()


async def test_an_empty_message_is_refused(tmp_path):
    postbox = _postbox(tmp_path)
    result = await _executor(tmp_path, postbox).execute(_tell(task="check-links", message="  "))
    assert result.error


async def test_a_long_message_is_capped_like_any_entry(tmp_path):
    postbox = _postbox(tmp_path)
    await _executor(tmp_path, postbox).execute(
        _tell(task="check-links", message="x" * 5000)
    )
    lines = (tmp_path / "check-links.md").read_text(encoding="utf-8").splitlines()
    assert len([line for line in lines if line.startswith("- ")]) == 1
    assert max(len(line) for line in lines) < 400


async def test_the_note_lands_where_the_recipient_will_see_it(tmp_path):
    """End to end with the delivery half: it arrives after their bookmark, and
    is not lost behind history that would otherwise have crowded it out."""
    postbox = _postbox(tmp_path)
    journal = tmp_path / "check-links.md"
    for i in range(50):
        append_journal(journal, "did", f"checked batch {i}", title="check links")
    await _executor(tmp_path, postbox).execute(
        _tell(task="check-links", message="rebuilt the docs")
    )
    shown = read_journal(journal)
    assert "rebuilt the docs" in shown.split("What you did before that")[0]


async def test_a_missing_recipient_journal_is_created(tmp_path):
    """A task that has never run has no journal yet; a note still reaches it."""
    postbox = _postbox(tmp_path)
    await _executor(tmp_path, postbox).execute(_tell(task="check-links", message="hello"))
    assert (tmp_path / "check-links.md").exists()


def test_notes_is_not_in_the_default_toolset():
    """On by default would let every task write into every other task's memory."""
    assert "notes" not in DEFAULT_TOOLSETS


def test_a_task_without_notes_has_no_such_tool(tmp_path):
    names = {d.name for d in LocalExecutor(tmp_path, DEFAULT_TOOLSETS).definitions()}
    assert "tell" not in names


def test_notes_without_a_postbox_declares_nothing(tmp_path):
    """`poieo run` on a bare graph has no roster; the tool must not half-exist."""
    names = {d.name for d in LocalExecutor(tmp_path, ["files", "notes"]).definitions()}
    assert "tell" not in names


async def test_the_other_toolsets_still_work_alongside_it(tmp_path):
    postbox = _postbox(tmp_path)
    (tmp_path / "a.txt").write_text("data")
    result = await _executor(tmp_path, postbox).execute(
        ToolCall(id="1", name="read_file", arguments={"path": "a.txt"})
    )
    # read_file numbers its lines now; what this test means is
    # that the executor handed the file's text back unchanged.
    assert result.text.endswith("data")
