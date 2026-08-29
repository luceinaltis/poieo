"""Photograph the board, for the README and the site.

    python tools/shots.py            # writes site/img/*.png

There is nothing to arrange by hand: this builds a whole poieo project in a
temporary folder -- a small git repository for the work to happen in, five
cards over it, and a scripted binding that spends nothing -- runs it until
there is history to look at, starts the daemon, and points the browser half
(tools/shots.js) at it. Nothing is written inside this repository except the
pictures.

The one thing it needs is a browser: `npm install --no-save playwright` first.

What ends up in the pictures is a real board doing real work. The models are
scripted, so a reader sees poieo's own behaviour rather than a mock-up of it:
the runs happen, the tools run, the change on `keep-tests-green` is a commit on
a branch in a private copy, and the diff in the picture is that commit's.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
POIEO = [sys.executable, str(REPO / "main.py")]
IMAGES = REPO / "site" / "img"

# The card whose run leaves a change behind, and so the one worth opening.
SUBJECT = "keep-tests-green"

# What a scripted call costs, in seconds. Fast while the history is being
# built, since nobody is watching it; slow while the pictures are taken, so a
# run is still in flight when the shutter opens and the workshop is at work
# rather than standing about.
QUICK, SLOW = 0.2, 6.0

WORKSHOP = {
    "README.md": """\
# workshop

A small project, kept in order by tasks that run while nobody is watching.
""",
    ".gitignore": "__pycache__/\n",
    "src/parse.py": '''\
def parse_duration(text):
    """Turn "30m" or "2h" into seconds."""
    unit = text[-1]
    amount = int(text[:-1])
    return amount * {"s": 1, "m": 60, "h": 3600}[unit]
''',
    "tests/test_parse.py": """\
from src.parse import parse_duration


def test_minutes():
    assert parse_duration("30m") == 1800


def test_days():
    assert parse_duration("2d") == 172800
""",
}

# One role per card, so no two read from the same script and the board says
# something different under each forge.
BINDING = """\
# A scripted stand-in, so the board can be photographed without spending a
# token. Every answer below is what some model would have said; everything
# poieo does with them is real.
name: workshop
version: 1

providers:
  scripted:
    type: mock
    options:
      latency: {latency}
      responses:
        green:
          - thinking: "Run the suite first and see what it says."
            tool_calls:
              - {{name: run_command, arguments: {{command: "python -m pytest -q"}}}}
          - thinking: "parse_duration has no case for days, and a test asks for one."
            tool_calls:
              - name: edit_file
                arguments:
                  path: src/parse.py
                  old: '{{"s": 1, "m": 60, "h": 3600}}'
                  new: '{{"s": 1, "m": 60, "h": 3600, "d": 86400}}'
          - "Added the missing day unit to parse_duration; the suite is green again."
        tidy:
          - tool_calls:
              - {{name: glob_files, arguments: {{pattern: "**/*.py"}}}}
          - "Nothing worth changing tonight -- the two modules here are already tidy."
        digest: "Four runs since Monday, three quiet and one with a change waiting for you."
        docs:
          - tool_calls:
              - {{name: read_file, arguments: {{path: README.md}}}}
          - "The README still describes what the code does. Nothing to do."
        issues:
          - "No new issues since the last run."
        "*": "(scripted)"

default:
  provider: scripted
  model: mock-model
"""

CARDS = {
    "keep-tests-green": (
        "keep the tests green",
        "green",
        "every: 30m",
        "Run the tests. If one fails, find out why and fix it.",
    ),
    "tidy-as-you-go": (
        "tidy as you go",
        "tidy",
        "every: 4h",
        "Find one thing worth tidying, tidy it, and leave the tests passing.",
    ),
    "weeks-digest": (
        "write the week's digest",
        "digest",
        "every: 12h",
        "Read the week's runs and write a paragraph a person could read at breakfast.",
    ),
    "stale-docs": (
        "watch for stale docs",
        "docs",
        "every: 6h",
        "Check whether the README still describes what the code does.",
    ),
    # Every card here is on an interval rather than a cron time, and that is
    # not an aesthetic choice: `poieo daemon --once` never returns while a task
    # holds a cron trigger -- `--once` sets `run_at_start`, the cron generator
    # ignores it, and the seeding below waits for 7am. Worth fixing in the
    # daemon; until then, seeding a board is not the place to find out.
    "answer-issues": (
        "answer the new issues",
        "issues",
        "every: 24h",
        "Read anything new in the tracker and draft an answer to each.",
    ),
}


def run(args: list[str], cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{' '.join(args[:3])} failed in {cwd}:\n{result.stdout}\n{result.stderr}")


def git(args: list[str], cwd: Path) -> None:
    run(["git", "-c", "user.email=board@example.com", "-c", "user.name=the board", *args], cwd)


def workshop_at(root: Path) -> Path:
    """The project the tasks work on: a real git repository, with real history.

    Real because the private copy is a git worktree and a change is a commit on
    a branch of it -- with no repository here there is nothing for a reader to
    accept in the morning, and the review half of the board photographs empty.
    """
    folder = root / "workshop"
    for name, body in WORKSHOP.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
    git(["init", "-q", "."], folder)
    git(["add", "-A"], folder)
    git(["commit", "-qm", "the workshop as it stood last night"], folder)
    return folder


def write_binding(board: Path, latency: float) -> None:
    (board / "models" / "default.yaml").write_text(BINDING.format(latency=latency), encoding="utf-8", newline="\n")


def project_at(root: Path, latency: float) -> Path:
    """A poieo project over that repository: five cards and a scripted binding."""
    board = root / "board"
    board.mkdir(parents=True, exist_ok=True)
    run([*POIEO, "init", "--mock"], board)
    (board / "tasks" / "hello.yaml").unlink()

    config = board / "poieo.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("name: board", "name: workshop"),
        encoding="utf-8",
        newline="\n",
    )
    write_binding(board, latency)

    for slug, (title, role, schedule, prompt) in CARDS.items():
        (board / "tasks" / f"{slug}.yaml").write_text(
            f"name: {title}\nfolder: ../../workshop\nrole: {role}\n{schedule}\nprompt: |\n  {prompt}\n",
            encoding="utf-8",
            newline="\n",
        )
    return board


def seed(board: Path, rounds: int = 3) -> None:
    """Give the board a past. Each round fires every task whose turn has come."""
    for _ in range(rounds):
        run([*POIEO, "daemon", "--once", "--no-web"], board)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def ask(base: str, path: str, body: bytes | None = None) -> dict:
    request = urllib.request.Request(base + path, data=body, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=10) as answer:
        return json.loads(answer.read() or b"{}")


def wait_for(base: str, daemon: subprocess.Popen, log: Path, seconds: float = 30) -> None:
    """Wait for the board, and say why if it never comes.

    The daemon is watched as well as the port: a config it refused to load, or
    a port it could not have, is over in a tenth of a second, and waiting the
    full thirty seconds to report "the board never answered" throws away the
    line that said what was actually wrong.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        if daemon.poll() is not None:
            raise SystemExit(f"the daemon stopped before it served anything:\n{said(log)}")
        try:
            ask(base, "/api/tasks")
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise SystemExit(f"the board never answered on {base}:\n{said(log)}")


def said(log: Path) -> str:
    return log.read_text(encoding="utf-8", errors="replace") if log.exists() else "(it said nothing at all)"


def main() -> int:
    root = Path(tempfile.gettempdir()) / "poieo-shots"
    # Every picture starts from an empty folder, and says so out loud when it
    # cannot. The last run's folder holds git worktrees, and on Windows a file
    # another process still has open makes the delete fail part-way -- and half
    # of the last board is worse than none: `init` would skip the files already
    # there, the workshop would have nothing new to commit, and the failure
    # would arrive several steps later wearing somebody else's clothes.
    shutil.rmtree(root, ignore_errors=True)
    if root.exists():
        raise SystemExit(f"{root} would not clear -- something still holds a file in it. Close it and run again.")
    root.mkdir(parents=True)

    # Every child of this script, seeding and daemon alike: the scripted model
    # runs the workshop's tests, and a pytest plugin installed globally on this
    # machine prints a deprecation warning -- naming a path under the
    # photographer's home folder -- before it says anything about the tests.
    # That is this machine in the picture rather than poieo, and the picture is
    # going in a public README.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    print("building a project to photograph ...")
    workshop_at(root)
    board = project_at(root, QUICK)
    seed(board)

    # Slow the model down for the photograph itself. An idle workshop is a
    # picture of nothing.
    write_binding(board, SLOW)

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    # To a file rather than a pipe. Nothing reads the daemon while the pictures
    # are being taken, and a pipe nobody drains fills and stops the process it
    # belongs to -- mid-photograph, which is the one place it would be hardest
    # to recognise.
    log = root / "daemon.log"
    daemon = subprocess.Popen(
        [*POIEO, "daemon", "--port", str(port)],
        cwd=board,
        stdout=log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    try:
        # Nothing is asked to run, and nothing is asked to stop. An interval
        # task fires the moment the daemon arms it, so by the time the board
        # answers the whole workshop is already at work -- which is what the
        # first picture is of, and why `/run` here would come back 409.
        wait_for(base, daemon, log)

        IMAGES.mkdir(parents=True, exist_ok=True)
        print(f"photographing {base} ...")
        shot = subprocess.run(["node", str(REPO / "tools" / "shots.js"), base, str(IMAGES), SUBJECT], cwd=REPO)
        if shot.returncode != 0:
            return shot.returncode
    finally:
        # kill after terminate, and never let the stopping raise: a
        # `TimeoutExpired` out of a `finally` replaces whatever went wrong
        # above with a complaint about the shutdown, and leaves the daemon up.
        daemon.terminate()
        try:
            daemon.wait(timeout=30)
        except subprocess.TimeoutExpired:
            daemon.kill()

    print(f"\nwrote {IMAGES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
