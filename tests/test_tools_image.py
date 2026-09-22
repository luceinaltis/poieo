"""Looking without touching: the `read` toolset, and a tool that sees a picture.

`read` is `files` without the half that writes, so a task can be given the
project to look at and nothing to change it with. `view_image` hands the model
a picture from the working directory; the model is shown it as an image,
beside a line of text saying what it was.
"""

from __future__ import annotations

import base64

import pytest
from test_runtime import agent_graph, mock_binding

from poieo.providers import ProviderPool
from poieo.providers.base import ToolCall
from poieo.runtime.executor import execute
from poieo.store import NullStore
from poieo.tools import TOOLSETS, LocalExecutor

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24


def _names(toolset):
    return {tool.definition.name for tool in TOOLSETS[toolset]}


def test_read_is_files_without_the_half_that_writes():
    assert _names("read") == {"read_file", "list_dir", "glob_files", "search_files", "view_image"}
    assert _names("read") < _names("files")
    assert {"write_file", "edit_file", "append_file"} <= _names("files") - _names("read")


async def _view(workdir, path):
    async with LocalExecutor(workdir, ["read"]) as executor:
        return await executor.execute(ToolCall(id="c1", name="view_image", arguments={"path": path}))


@pytest.mark.parametrize(("name", "body", "media_type"), [("a.png", PNG, "image/png"), ("b.jpg", JPEG, "image/jpeg")])
async def test_a_picture_is_seen_as_what_its_bytes_say(tmp_path, name, body, media_type):
    (tmp_path / name).write_bytes(body)

    result = await _view(tmp_path, name)

    assert not result.error
    assert name in result.text and media_type in result.text
    assert result.image == {"media_type": media_type, "data": base64.b64encode(body).decode("ascii")}


async def test_a_file_that_is_not_a_picture_is_refused_whatever_it_is_called(tmp_path):
    (tmp_path / "fake.png").write_text("just words")

    result = await _view(tmp_path, "fake.png")

    assert result.error
    assert result.image is None
    assert "not a PNG, JPEG, GIF or WebP" in result.text


async def test_a_picture_too_large_to_send_is_refused(tmp_path, monkeypatch):
    import poieo.tools.files as files

    monkeypatch.setattr(files, "_IMAGE_CAP", 16)
    (tmp_path / "big.png").write_bytes(PNG)

    result = await _view(tmp_path, "big.png")

    assert result.error and result.image is None
    assert "too large" in result.text


async def test_a_picture_outside_the_working_directory_is_refused(tmp_path):
    (tmp_path / "inside").mkdir()
    (tmp_path / "out.png").write_bytes(PNG)

    result = await _view(tmp_path / "inside", "../out.png")

    assert result.error and result.image is None


async def test_the_model_is_shown_the_picture_it_asked_to_see(tmp_path):
    (tmp_path / "shot.png").write_bytes(PNG)
    graph = agent_graph(tmp_path, tools=["read"])
    binding = mock_binding(
        {"worker": [{"tool_calls": [{"name": "view_image", "arguments": {"path": "shot.png"}}]}, "a black square"]}
    )
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    [seen] = [m for m in provider.calls[1].messages if m["role"] == "tool"]
    text, image = seen["content"]
    assert text["type"] == "text" and "shot.png" in text["text"]
    assert image == {"type": "image", "media_type": "image/png", "data": base64.b64encode(PNG).decode("ascii")}


async def test_a_tool_that_answers_in_words_is_still_a_string(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    graph = agent_graph(tmp_path, tools=["read"])
    binding = mock_binding(
        {"worker": [{"tool_calls": [{"name": "read_file", "arguments": {"path": "notes.txt"}}]}, "ok"]}
    )
    async with ProviderPool(binding) as pool:
        await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    [seen] = [m for m in provider.calls[1].messages if m["role"] == "tool"]
    assert isinstance(seen["content"], str)
