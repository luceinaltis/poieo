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
    assert set(TOOLSETS) == {"files", "shell", "notes"}
    # notes stays out of the default: on by default would let every task
    # write into every other task's memory from the day it is created.
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


import sys

from poieo.tools import ToolContext, Isolation, make_executor


async def test_local_executor_works_as_a_context_manager(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    async with LocalExecutor(tmp_path, DEFAULT_TOOLSETS) as ex:
        result = await ex.execute(ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}))
    assert result.text == "data"


async def test_make_executor_returns_local_without_hands(tmp_path):
    assert isinstance(make_executor(tmp_path, DEFAULT_TOOLSETS), LocalExecutor)


def test_make_executor_does_not_import_docker_without_isolation(tmp_path, monkeypatch):
    """The import lives inside the isolation branch, so the common path stays cheap.

    monkeypatch.delitem, not sys.modules.pop: a bare pop would leave the module
    unloaded for whatever test runs next, and re-importing it later would build
    a second DockerExecutor class that fails identity checks.
    """
    monkeypatch.delitem(sys.modules, "poieo.tools.docker", raising=False)
    make_executor(tmp_path, DEFAULT_TOOLSETS)
    assert "poieo.tools.docker" not in sys.modules


def test_make_executor_returns_a_boxed_executor_with_isolation(tmp_path):
    iso = Isolation(image="alpine:3.20")
    ex = make_executor(tmp_path, DEFAULT_TOOLSETS, ToolContext(isolation=iso))
    assert type(ex).__name__ == "DockerExecutor"
    assert ex.isolation == iso


def test_isolation_defaults_to_no_network():
    assert Isolation(image="x").network == "none"


def test_docker_available_treats_an_empty_version_as_unavailable(monkeypatch):
    """`docker info` exits 0 with an unreachable daemon on Windows and writes the
    failure to stderr, so the exit code alone says "available" when it is not.

    Left uncaught, the user is told to `docker pull` an image at 3am when the
    real problem is that docker is not running.
    """
    import subprocess

    from poieo.tools import docker as docker_module

    class _Done:
        returncode = 0
        stdout = "\n"
        stderr = 'error during connect: open //./pipe/dockerDesktopLinuxEngine'

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done())
    ok, reason = docker_module.docker_available()
    assert not ok
    assert "not running" in reason
