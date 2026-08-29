import pathlib
import shlex

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


async def test_a_truncated_read_says_how_to_see_the_rest(tmp_path):
    """`... [truncated]` is a dead end, and it stopped being one in #178.

    A file can be read in windows now, so a read that hit the ceiling should
    hand back the number to carry on from rather than leaving the model to
    guess that `offset` exists.
    """
    body = "".join("line %d" % n + chr(10) for n in range(1, 40_001))
    (tmp_path / "long.py").write_text(body)

    text = await TOOLS["read_file"].run(tmp_path, {"path": "long.py"})

    assert "truncated" in text
    assert "offset" in text
    # Cut on a line, not mid-word: half a line of code is a line of code that
    # does not exist, and `edit_file` matches on exact text.
    assert text.rstrip().splitlines()[-2].startswith(("1", "2", "3"))


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


async def test_read_numbers_the_lines(tmp_path):
    """Numbers are what make a range askable.

    Anthropic's text editor calls them "essential for successfully using the
    `view_range` parameter", and Claude Code's Read prints them too. The cost
    is that a model may copy one into an edit, which `edit_file` takes back
    off rather than failing on.
    """
    (tmp_path / "m.py").write_text("first\nsecond\n")

    text = await TOOLS["read_file"].run(tmp_path, {"path": "m.py"})

    assert "1\tfirst" in text
    assert "2\tsecond" in text


async def test_read_takes_a_range(tmp_path):
    """A step that read whole files ran its conversation to 271,064
    characters; one that read ranges never reached the cap at all. SWE-agent
    measured the same thing: showing whole files instead of a window cost 5.3
    points."""
    (tmp_path / "m.py").write_text("".join(f"line {n}\n" for n in range(1, 101)))

    text = await TOOLS["read_file"].run(
        tmp_path, {"path": "m.py", "offset": 40, "limit": 3}
    )

    assert "40\tline 40" in text
    assert "42\tline 42" in text
    assert "line 43" not in text
    assert "line 39" not in text


async def test_a_range_says_what_it_left_out(tmp_path):
    """A window with no edges reads like the whole file."""
    (tmp_path / "m.py").write_text("".join(f"line {n}\n" for n in range(1, 101)))

    text = await TOOLS["read_file"].run(
        tmp_path, {"path": "m.py", "offset": 40, "limit": 3}
    )

    assert "100" in text  # how many lines there are in total


async def test_a_range_past_the_end_says_so_rather_than_answering_nothing(tmp_path):
    """Silence would read as an empty file, and the model would believe it."""
    (tmp_path / "m.py").write_text("one\ntwo\n")

    text = await TOOLS["read_file"].run(tmp_path, {"path": "m.py", "offset": 900})

    assert text.strip()
    assert "2" in text


async def test_read_without_a_range_still_reads_the_whole_file(tmp_path):
    (tmp_path / "m.py").write_text("alpha\nbeta\n")
    text = await TOOLS["read_file"].run(tmp_path, {"path": "m.py"})
    assert "alpha" in text and "beta" in text


async def test_edit_replaces_the_one_place_it_matches(tmp_path):
    """Ten of seventy shell commands in a measured run were file surgery.

    `python -c "open(...,'a').write(...)"`, a patch script written and then
    deleted, a heredoc the Windows shell rejected outright. All of it because
    changing three lines of a file had no tool and rewriting the whole file
    was the only alternative.
    """
    (tmp_path / "m.py").write_text("a = 1\nb = 2\nc = 3\n")

    said = await TOOLS["edit_file"].run(
        tmp_path, {"path": "m.py", "old": "b = 2", "new": "b = 20"}
    )

    assert (tmp_path / "m.py").read_text() == "a = 1\nb = 20\nc = 3\n"
    assert "m.py" in said


async def test_edit_refuses_a_string_that_is_not_there(tmp_path):
    (tmp_path / "m.py").write_text("a = 1\n")
    with pytest.raises(ToolError, match="not find"):
        await TOOLS["edit_file"].run(
            tmp_path, {"path": "m.py", "old": "z = 9", "new": "z = 8"}
        )
    assert (tmp_path / "m.py").read_text() == "a = 1\n"


async def test_edit_refuses_an_ambiguous_string_and_says_how_many(tmp_path):
    """Ambiguity has to be an error rather than a guess.

    Quietly changing the first of three is the failure nobody notices until
    the tests do, and by then the run has moved on.
    """
    (tmp_path / "m.py").write_text("x = 0\nx = 0\nx = 0\n")
    with pytest.raises(ToolError, match="3 times"):
        await TOOLS["edit_file"].run(
            tmp_path, {"path": "m.py", "old": "x = 0", "new": "x = 1"}
        )
    assert (tmp_path / "m.py").read_text() == "x = 0\nx = 0\nx = 0\n"


async def test_edit_refuses_a_missing_file(tmp_path):
    with pytest.raises(ToolError, match="no such file"):
        await TOOLS["edit_file"].run(
            tmp_path, {"path": "gone.py", "old": "a", "new": "b"}
        )


async def test_edit_refuses_an_edit_that_changes_nothing(tmp_path):
    (tmp_path / "m.py").write_text("a = 1\n")
    with pytest.raises(ToolError):
        await TOOLS["edit_file"].run(
            tmp_path, {"path": "m.py", "old": "a = 1", "new": "a = 1"}
        )


async def test_edit_forgives_the_line_numbers_read_file_puts_on(tmp_path):
    """The reference harnesses hand this problem to the model.

    Anthropic's text editor numbers the lines it shows and tells the model to
    strip them; Claude Code's Edit says the same. A model that misses the
    instruction gets a silent failure. The tool takes the numbers off itself,
    because the model that needs the reminder is exactly the one that will
    miss it.
    """
    (tmp_path / "m.py").write_text("a = 1\nb = 2\n")

    await TOOLS["edit_file"].run(
        tmp_path, {"path": "m.py", "old": "     2\tb = 2", "new": "b = 20"}
    )

    assert (tmp_path / "m.py").read_text() == "a = 1\nb = 20\n"


async def test_edit_forgives_trailing_whitespace_and_line_endings(tmp_path):
    """Where the reported 50% edit failure rate on non-native models lives."""
    (tmp_path / "m.py").write_text("a = 1\r\nb = 2  \r\n", newline="")

    await TOOLS["edit_file"].run(
        tmp_path, {"path": "m.py", "old": "a = 1\nb = 2", "new": "a = 1\nb = 20"}
    )

    assert "b = 20" in (tmp_path / "m.py").read_text()


async def test_edit_does_not_forgive_indentation(tmp_path):
    """Trailing whitespace is forgiven; leading whitespace is not.

    In Python indentation is meaning. A model that sends the wrong depth means
    a different block, and a tool that shrugged would put the line somewhere
    the model did not ask for. (Matching *inside* a line is fine and stays
    fine -- `old` has never had to be a whole line.)
    """
    (tmp_path / "m.py").write_text("def f():\n    return 1\n")
    with pytest.raises(ToolError, match="could not find"):
        await TOOLS["edit_file"].run(
            tmp_path,
            {"path": "m.py", "old": "        return 1", "new": "        return 2"},
        )
    assert (tmp_path / "m.py").read_text() == "def f():\n    return 1\n"


async def test_edit_refuses_to_leave_a_python_file_unparseable(tmp_path):
    """Worth three points in SWE-agent's ablation, and free from the stdlib.

    A broken file is worse than a refused edit: the model finds out one test
    run later, and by then it is debugging its own typo instead of the task.
    """
    (tmp_path / "m.py").write_text("def f():\n    return 1\n")

    with pytest.raises(ToolError, match="would not parse"):
        await TOOLS["edit_file"].run(
            tmp_path, {"path": "m.py", "old": "    return 1", "new": "    return ("}
        )

    assert (tmp_path / "m.py").read_text() == "def f():\n    return 1\n"


async def test_edit_leaves_other_languages_to_their_own_tools(tmp_path):
    (tmp_path / "notes.md").write_text("# hi\nunbalanced (\n")
    await TOOLS["edit_file"].run(
        tmp_path, {"path": "notes.md", "old": "# hi", "new": "# hello ("}
    )
    assert "# hello (" in (tmp_path / "notes.md").read_text()


async def test_append_adds_to_the_end(tmp_path):
    """Four of the five file surgeries in the run were appends, not replaces.

    `cat >> file << 'EOF'` (which the Windows shell rejected), and a
    write-a-temp-file-then-append-it-then-delete-it dance. Both are one call.
    """
    (tmp_path / "log.md").write_text("first\n")

    await TOOLS["append_file"].run(tmp_path, {"path": "log.md", "content": "second\n"})

    assert (tmp_path / "log.md").read_text() == "first\nsecond\n"


async def test_append_refuses_a_missing_file(tmp_path):
    # Creating a file is `write_file`'s job, and a typo in a path should not
    # quietly become a new file nobody asked for.
    with pytest.raises(ToolError, match="no such file"):
        await TOOLS["append_file"].run(tmp_path, {"path": "gone.md", "content": "x"})


from poieo.tools.shell import SHELL_TOOLS, posix_shell

SHELL = {t.definition.name: t for t in SHELL_TOOLS}

# What a command may assume it is being read by. The question is no longer
# which OS this is -- it is whether a POSIX shell was found, which on Windows
# is usually yes and used to be irrelevant.
POSIX = __import__("os").name != "nt" or bool(posix_shell())


def test_a_posix_shell_is_preferred_when_there_is_one(monkeypatch):
    """A model writes POSIX because that is what its training and this
    repository's own documents are written in. Where a POSIX shell exists,
    running commands anywhere else is a translation nobody asked for."""
    import poieo.tools.shell as shell

    monkeypatch.setattr(shell.shutil, "which", lambda name: "C:/Program Files/Git/bin/bash.exe")
    assert posix_shell(windows=True) == "C:/Program Files/Git/bin/bash.exe"


def test_the_wsl_launcher_is_not_a_posix_shell_for_this_purpose(monkeypatch):
    """`C:\\Windows\\System32\\bash.exe` starts a Linux distribution.

    Commands would run against a different filesystem, so the workdir handed
    to `cwd` would point somewhere else entirely -- and the command would
    *succeed* there. Running quietly in the wrong place is worse than failing.
    """
    import poieo.tools.shell as shell

    monkeypatch.setattr(
        shell.shutil, "which", lambda name: "C:\\Windows\\System32\\bash.exe"
    )
    assert posix_shell(windows=True) is None


def test_without_a_posix_shell_there_is_none_to_report(monkeypatch):
    import poieo.tools.shell as shell

    monkeypatch.setattr(shell.shutil, "which", lambda name: None)
    assert posix_shell(windows=True) is None


def test_the_tool_says_which_shell_it_will_use():
    """Nothing told the model what it was talking to.

    In a measured run the model saw `grep` and `sed` work -- the binaries are
    on PATH -- concluded it was on a POSIX system, wrote a heredoc, and got
    `<<은(는) 예상되지 않았습니다` back from cmd.exe. Claude Code's own shell
    tool opens by naming its shell for this reason.
    """
    described = SHELL["run_command"].definition.description
    # One or the other, and never neither: a model that is told nothing
    # assumes POSIX, which is how the heredoc above came to be written.
    assert ("POSIX shell" in described) != ("cmd.exe" in described)


async def test_a_heredoc_runs(tmp_path):
    """POSIX syntax the model actually reached for, and cmd.exe rejected.

    On Linux and macOS this has always passed and proves nothing. On Windows
    it is red before this change and green after, which is the whole point of
    it being here.
    """
    result = await SHELL["run_command"].run(
        tmp_path,
        {"command": "cat > out.txt << 'EOF'\nhello\nEOF"},
    )

    assert "exit code: 0" in result
    assert (tmp_path / "out.txt").read_text().strip() == "hello"


async def test_run_command_reports_exit_code_and_output(tmp_path):
    out = await SHELL["run_command"].run(tmp_path, {"command": "echo hello"})
    assert out.startswith("exit code: 0")
    assert "hello" in out


async def test_run_command_nonzero_exit_is_reported_not_raised(tmp_path):
    out = await SHELL["run_command"].run(tmp_path, {"command": "exit 3"})
    assert out.startswith("exit code: 3")


async def test_run_command_runs_in_workdir(tmp_path):
    (tmp_path / "here.txt").write_text("x")
    out = await SHELL["run_command"].run(
        tmp_path, {"command": "ls" if POSIX else "dir /b"}
    )
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
    # read_file numbers its lines now; what this test means is
    # that the executor handed the file's text back unchanged.
    assert result.text.endswith("data")


async def test_executor_turns_failures_into_error_results(tmp_path):
    ex = LocalExecutor(tmp_path, DEFAULT_TOOLSETS)
    missing = await ex.execute(ToolCall(id="1", name="read_file", arguments={"path": "nope"}))
    assert missing.error and "nope" in missing.text
    unknown = await ex.execute(ToolCall(id="2", name="fly", arguments={}))
    assert unknown.error and "fly" in unknown.text
    bad_args = await ex.execute(ToolCall(id="3", name="read_file", arguments={}))
    assert bad_args.error


import sys

from poieo.tools import Isolation, ToolContext, make_executor


async def test_local_executor_works_as_a_context_manager(tmp_path):
    (tmp_path / "a.txt").write_text("data")
    async with LocalExecutor(tmp_path, DEFAULT_TOOLSETS) as ex:
        result = await ex.execute(ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}))
    # read_file numbers its lines now; what this test means is
    # that the executor handed the file's text back unchanged.
    assert result.text.endswith("data")


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


# -- compiled scripts: the build happens once --------------------------------
#
# This machine has no `cc` and no `go` -- checked. So these drive the compiler
# through a recording stub rather than really building, the same way the boxed
# tests drive `_docker`. What is under test is the argv and the cache decision,
# which is all this feature is.


def _with_stub_compiler(monkeypatch, tmp_path):
    """A LocalExecutor whose subprocesses are recorded, not run."""
    from poieo.tools import CommandResult, LocalExecutor, ToolContext

    cache = tmp_path / "cache"
    executor = LocalExecutor(
        tmp_path / "work", ["shell"], ToolContext(build_cache=cache)
    )
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)

    ran: list[str] = []

    async def fake(command, timeout=None, env=None, stdin=None):
        ran.append(command)
        # A build leaves a binary behind, as a real compiler would. Read the
        # line as a shell would rather than by hand: how a path is quoted is
        # the shell's business, and a temp path really does contain "-of".
        argv = shlex.split(command, posix=True)
        if "-o" in argv:
            target = argv[argv.index("-o") + 1]
            pathlib.Path(target).write_text("binary", encoding="utf-8")
        return CommandResult(exit_code=0, output="")

    monkeypatch.setattr(executor, "run_command", fake)
    return executor, ran, cache


async def test_the_same_script_is_built_once(tmp_path, monkeypatch):
    """The whole claim. Second run finds the binary and skips the compiler."""
    executor, ran, _ = _with_stub_compiler(monkeypatch, tmp_path)
    code = "int main(void){return 0;}"

    await executor.run_script("c", code)
    await executor.run_script("c", code)

    builds = [c for c in ran if c.startswith("cc ")]
    assert len(builds) == 1, ran
    # ...and it ran both times.
    assert len(ran) == 3


async def test_changing_the_script_builds_again(tmp_path, monkeypatch):
    executor, ran, _ = _with_stub_compiler(monkeypatch, tmp_path)

    await executor.run_script("c", "int main(void){return 0;}")
    await executor.run_script("c", "int main(void){return 1;}")

    assert len([c for c in ran if c.startswith("cc ")]) == 2


async def test_the_build_never_touches_the_workdir(tmp_path, monkeypatch):
    """The workdir is committed whole as the night's change, so a source file
    or a binary left there would arrive in somebody's morning diff."""
    executor, _, cache = _with_stub_compiler(monkeypatch, tmp_path)

    await executor.run_script("c", "int main(void){return 0;}")

    assert list((tmp_path / "work").iterdir()) == []
    assert list(cache.rglob("main.c"))


async def test_an_interpreted_script_still_goes_over_stdin(tmp_path, monkeypatch):
    """No file, no cache, nothing to build -- the #175 path is untouched."""
    executor, ran, cache = _with_stub_compiler(monkeypatch, tmp_path)

    await executor.run_script("python", "print(1)")

    assert ran == ["python -"]
    assert not cache.exists()


async def test_the_box_builds_inside_itself(tmp_path, monkeypatch):
    """Not on a mounted host folder. A binary built in the image is for the
    image's platform, and a cache shared with the host would eventually hand a
    Windows executable to a Linux container."""
    from poieo.tools import docker as dock

    executor, seen, fed = _boxed(monkeypatch, tmp_path)

    async def miss(*args: str, timeout: float = 0, stdin: str | None = None):
        seen.append(args)
        fed.append(stdin)
        # `test -x` says no; everything else succeeds. A cache miss, in full.
        return (1 if "test -x" in args[-1] else 0), ""

    monkeypatch.setattr(dock, "_docker", miss)
    await executor.run_script("c", "int main(void){return 0;}")

    joined = " ".join(" ".join(a) for a in seen)
    assert "/tmp/poieo-build/" in joined
    # The source went in over stdin, and no host path was mounted for it.
    assert "int main(void){return 0;}" in [f for f in fed if f]
    assert str(tmp_path) not in joined


async def test_the_box_skips_a_build_it_already_has(tmp_path, monkeypatch):
    """`test -x` answering 0 means the binary is there, so no compiler runs."""
    from poieo.tools import docker as dock

    executor, seen, _fed = _boxed(monkeypatch, tmp_path)

    async def already_built(*args: str, timeout: float = 0, stdin: str | None = None):
        seen.append(args)
        return 0, ""  # every exec succeeds, including `test -x`

    monkeypatch.setattr(dock, "_docker", already_built)
    await executor.run_script("c", "int main(void){return 0;}")

    joined = " ".join(" ".join(a) for a in seen)
    assert "cc " not in joined


async def test_a_compiled_script_reaches_the_compiler_verbatim(tmp_path, monkeypatch):
    """`{{` belongs to the language here. A nested initializer is ordinary C,
    and anything that rendered it would hand the compiler a different program
    than the one written."""
    executor, _, cache = _with_stub_compiler(monkeypatch, tmp_path)
    code = "int m[2][2] = {{1, 0}, {0, 1}};\nint main(void){return m[0][0];}"

    await executor.run_script("c", code)

    written = list(cache.rglob("main.c"))
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8") == code


@pytest.mark.parametrize("folder", ["cache", "cache with a space"])
async def test_a_built_binary_is_actually_runnable(tmp_path, monkeypatch, folder):
    """Through the real shell, which is the only thing that can say whether a
    path was spelled right. A quoted Windows path with no space in it loses its
    quotes before bash sees it and dies as an unterminated string; an unquoted
    one loses its backslashes. Both build fine and fail at the last step."""
    from poieo.tools import CommandResult, LocalExecutor, ToolContext

    cache = tmp_path / folder
    executor = LocalExecutor(tmp_path, ["shell"], ToolContext(build_cache=cache))

    async def compiler(command, timeout=None, env=None, stdin=None):
        # Stand in for `cc`: write something the shell can really execute.
        if command.startswith("cc "):
            # Read it as a shell would: the path may hold a space, which is
            # the case this test exists for.
            argv = shlex.split(command, posix=True)
            target = pathlib.Path(argv[argv.index("-o") + 1])
            target.write_text("#!/bin/sh\necho ran-ok\n", encoding="utf-8")
            target.chmod(0o755)
            return CommandResult(exit_code=0, output="")
        return await real(command, timeout=timeout, env=env, stdin=stdin)

    real = executor.run_command
    monkeypatch.setattr(executor, "run_command", compiler)

    result = await executor.run_script("c", "int main(void){return 0;}")

    assert result.exit_code == 0, result.output
    assert "ran-ok" in result.output
