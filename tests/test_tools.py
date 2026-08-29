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


async def test_search_reports_the_file_the_line_and_the_line_number(tmp_path):
    """Searching a repository was the shell's job and it should not have been.

    Twenty-three of seventy shell commands in a measured run were `grep`, and
    the POSIX spelling of one of them died on a Windows shell -- the same
    dialect problem the `env` argument exists to keep out of the tool.
    """
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text("import os\nDEBUG = True\n")
    (tmp_path / "other.py").write_text("DEBUG = False\n")

    found = await TOOLS["search_files"].run(tmp_path, {"pattern": "DEBUG"})

    lines = found.replace("\\", "/").splitlines()
    assert "pkg/m.py:2: DEBUG = True" in lines
    assert "other.py:1: DEBUG = False" in lines


async def test_search_narrows_by_glob(tmp_path):
    (tmp_path / "a.py").write_text("needle\n")
    (tmp_path / "b.txt").write_text("needle\n")

    found = await TOOLS["search_files"].run(
        tmp_path, {"pattern": "needle", "glob": "**/*.py"}
    )

    assert "a.py" in found
    assert "b.txt" not in found


async def test_search_stays_out_of_dot_directories(tmp_path):
    """A run's folder is a git copy, and `.git` is full of packs and objects.

    Matching inside them fills the answer with noise the model cannot act on,
    and the packs are binary besides.
    """
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "COMMIT_EDITMSG").write_text("needle\n")
    (tmp_path / "kept.py").write_text("needle\n")

    found = await TOOLS["search_files"].run(tmp_path, {"pattern": "needle"})

    assert "kept.py" in found
    assert "COMMIT_EDITMSG" not in found


async def test_search_skips_files_it_cannot_read_as_text(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\x00\xff needle \x00")
    (tmp_path / "plain.txt").write_text("needle\n")

    found = await TOOLS["search_files"].run(tmp_path, {"pattern": "needle"})

    assert "plain.txt" in found
    assert "blob.bin" not in found


async def test_search_says_how_much_it_left_out(tmp_path):
    """An unbounded search refills the conversation the clearing just emptied.

    In SWE-agent's own ablation an unsummarized, iterative search scored six
    points *below* having no search at all.
    """
    (tmp_path / "many.txt").write_text("needle\n" * 500)

    found = await TOOLS["search_files"].run(
        tmp_path, {"pattern": "needle", "max_results": 5}
    )

    assert len(
        [line for line in found.splitlines() if line.startswith("many.txt:")]
    ) == 5
    assert "495 more" in found


async def test_search_clips_a_very_long_line(tmp_path):
    (tmp_path / "wide.txt").write_text("needle " + "x" * 5000 + "\n")

    found = await TOOLS["search_files"].run(tmp_path, {"pattern": "needle"})

    assert len(found.splitlines()[0]) < 500


async def test_search_answers_a_broken_pattern_rather_than_raising(tmp_path):
    """`docs/tools.md`: failure is text the model can read and correct."""
    (tmp_path / "a.txt").write_text("x\n")
    with pytest.raises(ToolError, match="pattern"):
        await TOOLS["search_files"].run(tmp_path, {"pattern": "(unclosed"})


async def test_search_rejects_an_escaping_glob(tmp_path):
    with pytest.raises(ToolError):
        await TOOLS["search_files"].run(
            tmp_path, {"pattern": "x", "glob": "../**/*.py"}
        )


async def test_search_says_so_when_nothing_matches(tmp_path):
    (tmp_path / "a.txt").write_text("nothing here\n")
    found = await TOOLS["search_files"].run(tmp_path, {"pattern": "needle"})
    assert found == "(no matches)"


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


async def test_run_command_takes_env_without_shell_syntax(tmp_path):
    """Setting a variable for one command is the commonest thing a gate needs,
    and every shell spells it differently. `VAR=1 cmd` is a syntax error on
    Windows, where cmd reads `VAR=1` as the program to run and fails with the
    same exit code a program that ran and failed would -- so a step told to run
    one exact command cannot tell "this did not start" from "this went red"."""
    out = await SHELL["run_command"].run(
        tmp_path,
        {"command": "python -c \"import os; print(os.environ['POIEO_PROBE'])\"",
         "env": {"POIEO_PROBE": "set-by-the-tool"}},
    )

    assert out.startswith("exit code: 0")
    assert "set-by-the-tool" in out


async def test_run_command_env_adds_to_the_environment_rather_than_replacing_it(tmp_path):
    """The command still needs a PATH to find anything at all."""
    out = await SHELL["run_command"].run(
        tmp_path,
        {"command": "python -c \"import os; print('PATH' in os.environ)\"",
         "env": {"POIEO_PROBE": "x"}},
    )

    assert "True" in out


async def test_run_command_env_values_are_strings(tmp_path):
    """A number in JSON is a number, and an environment takes neither None nor
    ints -- the tool coerces rather than raising at the model."""
    out = await SHELL["run_command"].run(
        tmp_path,
        {"command": "python -c \"import os; print(os.environ['POIEO_N'])\"",
         "env": {"POIEO_N": 7}},
    )

    assert out.startswith("exit code: 0")
    assert "7" in out


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


# -- the seam answers with a number, not a sentence --------------------------


async def test_the_executor_runs_a_command_and_reports_the_code_as_a_number(tmp_path):
    """`run_command` hands the model `exit code: 0\n...` because a model reads
    text. A graph does not: a router testing `check.exit_code == 0` needs the
    number the process actually returned, not a sentence about it.

    Both are the same run. This is the seam answering directly.
    """
    from poieo.tools import make_executor

    async with make_executor(tmp_path, ["shell"]) as executor:
        result = await executor.run_command("exit 3")

    assert result.exit_code == 3
    assert isinstance(result.exit_code, int)


async def test_the_executor_reports_output_without_the_prefix(tmp_path):
    from poieo.tools import make_executor

    async with make_executor(tmp_path, ["shell"]) as executor:
        result = await executor.run_command("echo hello")

    assert result.exit_code == 0
    assert "hello" in result.output
    # The prefix belongs to the text a model reads, not to the output itself.
    assert not result.output.startswith("exit code:")


async def test_the_tool_and_the_seam_are_the_same_run(tmp_path):
    """One implementation, two shapes. If they drifted, the model and the graph
    would disagree about what a command did."""
    from poieo.tools import make_executor

    async with make_executor(tmp_path, ["shell"]) as executor:
        direct = await executor.run_command("exit 7")
        through_tool = await SHELL["run_command"].run(tmp_path, {"command": "exit 7"})

    assert through_tool.startswith(f"exit code: {direct.exit_code}")


async def test_the_seam_takes_env_and_timeout_like_the_tool_does(tmp_path):
    from poieo.tools import make_executor

    async with make_executor(tmp_path, ["shell"]) as executor:
        result = await executor.run_command(
            "python -c \"import os; print(os.environ['POIEO_PROBE'])\"",
            env={"POIEO_PROBE": "through-the-seam"},
        )

    assert result.exit_code == 0
    assert "through-the-seam" in result.output


async def test_a_command_that_could_not_run_still_raises(tmp_path):
    """A timeout is not an exit code. "this never finished" and "this finished
    badly" are different facts and a graph must be able to tell them apart."""
    from poieo.tools import ToolError, make_executor

    async with make_executor(tmp_path, ["shell"]) as executor:
        with pytest.raises(ToolError, match="timed out"):
            await executor.run_command("python -c \"import time; time.sleep(5)\"", timeout=0.3)


# -- the boxed seam, without needing a box -----------------------------------
#
# tests/test_tools_docker.py needs a real docker and skips without one, so the
# argv the container path builds would otherwise go unchecked on most machines.


def _boxed(monkeypatch, tmp_path):
    """A DockerExecutor with its docker calls recorded instead of run."""
    from poieo.tools import Isolation
    from poieo.tools import docker as dock

    seen: list[tuple[str, ...]] = []
    fed: list[str | None] = []

    async def fake(*args: str, timeout: float = 0, stdin: str | None = None):
        seen.append(args)
        fed.append(stdin)
        return 3, "boxed output"

    monkeypatch.setattr(dock, "_docker", fake)
    executor = dock.DockerExecutor(
        tmp_path, ["shell"], image="x", network="none", user=None
    )
    executor.container_id = "cafe1234"
    return executor, seen, fed


async def test_the_boxed_seam_reports_the_code_as_a_number(tmp_path, monkeypatch):
    executor, _, _fed = _boxed(monkeypatch, tmp_path)

    result = await executor.run_command("exit 3")

    assert result.exit_code == 3
    assert result.output == "boxed output"


async def test_the_boxed_seam_passes_env_to_the_container(tmp_path, monkeypatch):
    """`env` reached the host path and was dropped on the way into a box, so a
    task that asked to be fenced silently lost the one thing #154 added to stop
    a gate reporting a suite it never ran."""
    executor, seen, fed = _boxed(monkeypatch, tmp_path)

    await executor.run_command("pytest", env={"POIEO_PROBE": "1"})

    argv = seen[0]
    assert "-e" in argv
    assert "POIEO_PROBE=1" in argv
    # ...and it is still an exec into this container, in the mounted workdir.
    assert argv[0] == "exec" and "cafe1234" in argv


async def test_the_boxed_tool_and_the_boxed_seam_agree(tmp_path, monkeypatch):
    executor, _, _fed = _boxed(monkeypatch, tmp_path)

    text = await executor._run_command_in_box(tmp_path, {"command": "exit 3"})

    assert text.startswith("exit code: 3")
    assert "boxed output" in text


# -- a script goes to the interpreter, not through a shell -------------------


async def test_the_seam_feeds_a_script_on_stdin(tmp_path):
    """Quotes, a colon and newlines all at once -- the case that does not even
    parse as a `command:` in YAML, and would be mangled by a shell if it did."""
    from poieo.tools import make_executor

    code = "import json\nprint(json.dumps({'k': 'v'}))\n"
    async with make_executor(tmp_path, ["shell"]) as executor:
        result = await executor.run_command("python -", stdin=code)

    assert result.exit_code == 0
    assert '"k": "v"' in result.output


async def test_a_scripts_exit_code_is_the_processs_own(tmp_path):
    from poieo.tools import make_executor

    async with make_executor(tmp_path, ["shell"]) as executor:
        result = await executor.run_command("python -", stdin="import sys\nsys.exit(4)\n")

    assert result.exit_code == 4


async def test_the_boxed_seam_feeds_stdin_interactively(tmp_path, monkeypatch):
    """`docker exec` needs `-i` or the interpreter reads an empty stdin and
    exits 0 having run nothing -- success over no work, again."""
    executor, seen, fed = _boxed(monkeypatch, tmp_path)

    await executor.run_command("python -", stdin="print(1)")

    argv = seen[0]
    assert "-i" in argv
    assert argv[0] == "exec"
    # ...and the code itself actually went down the pipe.
    assert fed[0] == "print(1)"
