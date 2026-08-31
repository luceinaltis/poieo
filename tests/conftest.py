import asyncio
import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXAMPLES = ROOT / "examples"

# Derived, gitignored, and sometimes large. A copy of the sample project does
# not want yesterday's run log along with it.
_DERIVED = shutil.ignore_patterns("runs", "worktrees", "__pycache__")

from poieo.layout import Layout  # noqa: E402  (needs the path above)
from poieo.tools.shell import posix_shell  # noqa: E402

# What a command a test writes may assume it is being read by. The question is
# not which OS this is: `run_command` sends the command to a POSIX shell when
# it can find one, and on Windows it usually can. Two test modules were asking
# it and only one had the current answer -- the other still said "Windows means
# cmd.exe", which was true until a POSIX shell became the first choice, and it
# spent that time passing for the wrong reason on the machine this is built on.
POSIX = os.name != "nt" or bool(posix_shell())


@pytest.fixture
def sample_project(tmp_path) -> Path:
    """A copy of ``examples/``, for a test that actually *runs* it.

    Running a card appends to its journal, so a test that ran the shipped
    project in place wrote into files that are in git -- and twice, a run's
    output was committed by accident. The copy keeps what these tests are for,
    which is proving the example project a reader is handed really works.

    Tests that only ask the sample project questions -- where its store is,
    what its cards are called -- can go on reading :data:`EXAMPLES` directly.
    """
    root = tmp_path / "examples"
    shutil.copytree(EXAMPLES, root, ignore=_DERIVED)
    return root


def _fingerprint(root: Path) -> dict[str, str]:
    """Every tracked-shaped file under ``root``, by content.

    Derived folders are skipped **by their path relative to the root**, never
    by the absolute one: this repository is normally checked out inside
    `.claude/worktrees/`, so an absolute-path test for "worktrees" skips every
    file there is and the guard silently passes on an empty set.
    """
    prints = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if {"runs", "worktrees", "__pycache__"} & set(relative.parts):
            continue
        prints[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return prints


@pytest.fixture(scope="session", autouse=True)
def examples_stay_clean():
    """Fail the session if the suite wrote into the shipped example project.

    It is a folder a person owns and git tracks, and the damage is quiet: a
    journal grows by a line, nobody notices, and eventually a run's mock output
    rides into a commit. That happened twice before anybody looked. Catching it
    here costs one hash of a small folder, twice.
    """
    before = _fingerprint(EXAMPLES)
    yield
    after = _fingerprint(EXAMPLES)
    touched = sorted(
        set(before) ^ set(after) | {path for path in before.keys() & after.keys() if before[path] != after[path]}
    )
    assert not touched, (
        "the suite wrote into examples/, which is in git: "
        + ", ".join(touched)
        + ". Use the `sample_project` fixture to run the example project in a copy."
    )


def at(root) -> Layout:
    """Where a project keeps things, for a root the test already knows.

    Tests used to spell `tmp_path / "tasks" / "memory" / "facts"` by hand, in
    six files. Asking the same object the code asks means the next time the
    layout moves, the tests follow from one place -- and a test that quietly
    checked the wrong folder would have been the worst kind of green.
    """
    return Layout(root=Path(root))


def remember(project, slug: str, text: str, writer: str = "person"):
    """One learned entry, said the way a person would say it.

    A test writes what an entry *is* -- optional frontmatter, then a body --
    and this is the single place that shape becomes the row the memory keeps.
    Six files used to hand-write the file the memory was made of; now the
    shape lives here and only here, so moving it again moves one function.
    """
    import yaml

    from poieo.memory import frontmatter, write_entry

    matter: dict = {}
    body = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                matter = yaml.safe_load("\n".join(lines[1:i])) or {}
                body = "\n".join(lines[i + 1 :])
                break
    return write_entry(project, slug, body, frontmatter(matter), writer=writer)


async def up(daemon):
    """Start serving, and hand the task back once the runners exist.

    A daemon is up when it has loaded what it is going to run, not when
    `serve()` has been scheduled -- a test that asserted on `daemon.runners`
    straight after `create_task` was reading an empty list on a fast machine
    and the right one on a slow one.
    """
    task = asyncio.create_task(daemon.serve(install_signals=False))
    while not daemon.runners:
        await asyncio.sleep(0.01)
    return task


async def until(predicate, what="the condition", timeout=5.0):
    """Wait for something the daemon does on its own, or say what never came.

    Every one of these tests waits on a background loop rather than on a
    return value, so the failure to design for is the one that hangs. The
    deadline turns that into a named assertion, which is the difference
    between a red suite and a suite somebody kills after ten minutes.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


async def down(daemon, task):
    """Stop it and wait for the serve task, so nothing outlives the test."""
    daemon.stop()
    return await asyncio.wait_for(task, timeout=10)


def card(folder, name: str, body: str = "") -> Path:
    """One job, as its own file.

    A job is declared one way -- a card in the tasks folder -- so the tests
    declare them that way too. `body` is the rest of the card's YAML; the name
    and the folder it lives in are the two things every one of them needs.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.yaml"
    path.write_text(f"name: {name}\n{body}", encoding="utf-8")
    return path
