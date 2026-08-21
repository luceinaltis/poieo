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


from poieo.tools.shell import SHELL_TOOLS

SHELL = {t.definition.name: t for t in SHELL_TOOLS}


async def test_run_command_reports_exit_code_and_output(tmp_path):
    out = await SHELL["run_command"].run(tmp_path, {"command": "echo hello"})
    assert out.startswith("exit code: 0")
    assert "hello" in out


async def test_run_command_nonzero_exit_is_reported_not_raised(tmp_path):
    out = await SHELL["run_command"].run(tmp_path, {"command": "exit 3"})
    assert out.startswith("exit code: 3")


async def test_run_command_runs_in_workdir(tmp_path):
    (tmp_path / "here.txt").write_text("x")
    out = await SHELL["run_command"].run(tmp_path, {"command": "dir /b" if __import__("os").name == "nt" else "ls"})
    assert "here.txt" in out


async def test_run_command_times_out(tmp_path):
    import os
    sleeper = "ping -n 30 127.0.0.1 > NUL" if os.name == "nt" else "sleep 30"
    with pytest.raises(ToolError, match="timed out"):
        await SHELL["run_command"].run(tmp_path, {"command": sleeper, "timeout": 1})


from poieo.providers.base import ToolCall
from poieo.tools import DEFAULT_TOOLSETS, TOOLSETS, LocalExecutor


def test_registry_names():
    assert set(TOOLSETS) == {"files", "shell"}
    assert DEFAULT_TOOLSETS == ["files", "shell"]


def test_executor_declares_selected_toolsets(tmp_path):
    only_files = LocalExecutor(tmp_path, ["files"])
    names = {d.name for d in only_files.definitions()}
    assert "read_file" in names and "run_command" not in names


async def test_executor_runs_a_call(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    ex = LocalExecutor(tmp_path, DEFAULT_TOOLSETS)
    result = await ex.execute(ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}))
    assert not result.error
    assert result.text == "data"


async def test_executor_turns_failures_into_error_results(tmp_path):
    ex = LocalExecutor(tmp_path, DEFAULT_TOOLSETS)
    missing = await ex.execute(ToolCall(id="1", name="read_file", arguments={"path": "nope"}))
    assert missing.error and "nope" in missing.text
    unknown = await ex.execute(ToolCall(id="2", name="fly", arguments={}))
    assert unknown.error and "fly" in unknown.text
    bad_args = await ex.execute(ToolCall(id="3", name="read_file", arguments={}))
    assert bad_args.error
