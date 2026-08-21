import pytest

from poieo.tools import ToolError
from poieo.tools.files import FILES_TOOLS, resolve_path

TOOLS = {t.definition.name: t for t in FILES_TOOLS}


def test_resolve_path_blocks_escapes(tmp_path):
    (tmp_path / "inner").mkdir()
    assert resolve_path(tmp_path, "inner/a.txt") == tmp_path / "inner" / "a.txt"
    for raw in ("../outside.txt", "inner/../../outside.txt"):
        with pytest.raises(ToolError):
            resolve_path(tmp_path, raw)


def test_resolve_path_blocks_absolute_paths_outside(tmp_path):
    with pytest.raises(ToolError):
        resolve_path(tmp_path, str(tmp_path.parent / "elsewhere.txt"))
    # An absolute path *inside* the workdir is fine.
    assert resolve_path(tmp_path, str(tmp_path / "ok.txt")) == tmp_path / "ok.txt"


async def test_read_write_roundtrip(tmp_path):
    await TOOLS["write_file"].run(tmp_path, {"path": "notes/a.txt", "content": "hello"})
    text = await TOOLS["read_file"].run(tmp_path, {"path": "notes/a.txt"})
    assert "hello" in text


async def test_read_missing_file_raises_tool_error(tmp_path):
    with pytest.raises(ToolError, match="a.txt"):
        await TOOLS["read_file"].run(tmp_path, {"path": "a.txt"})


async def test_read_truncates_large_files(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 250_000)
    text = await TOOLS["read_file"].run(tmp_path, {"path": "big.txt"})
    assert len(text) < 210_000
    assert "truncated" in text


async def test_list_dir_and_glob(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text("x = 1")
    (tmp_path / "top.txt").write_text("t")
    listing = await TOOLS["list_dir"].run(tmp_path, {})
    assert "pkg" in listing and "top.txt" in listing
    found = await TOOLS["glob_files"].run(tmp_path, {"pattern": "**/*.py"})
    assert "pkg/m.py" in found.replace("\\", "/")


async def test_glob_rejects_escaping_pattern(tmp_path):
    with pytest.raises(ToolError):
        await TOOLS["glob_files"].run(tmp_path, {"pattern": "../**/*.py"})
