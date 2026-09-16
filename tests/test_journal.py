"""The journal has a module of its own, below everything that writes to it.

A run's outcome, a review decision and a note from another task all land in
one append-only file per task, and the card reads it into the prompt. None of
those writers should have to load the card to reach it.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fresh(probe: str) -> subprocess.CompletedProcess:
    """A fresh interpreter, because the suite has imported everything already;
    ``PYTHONPATH`` pins it to this checkout rather than whatever ``pip install
    -e`` last pointed at."""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env)


def test_the_journal_loads_without_the_card_or_the_memory():
    result = _fresh(
        "import sys\n"
        "import poieo.journal\n"
        "print(sorted(name for name in sys.modules if name.startswith(('poieo.card', 'poieo.memory'))))\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout


def test_leaving_a_note_for_another_task_does_not_load_the_card(tmp_path):
    """`tell` is a tool, and writing the recipient's line is the tool's own job."""
    probe = (
        "import asyncio, sys\n"
        "from pathlib import Path\n"
        "from poieo.tools.notes import Postbox, notes_tools\n"
        f"folder = Path({str(tmp_path)!r})\n"
        "recipients = {'build-docs': folder / 'build-docs.md', 'check-links': folder / 'check-links.md'}\n"
        "(tell,) = notes_tools(Postbox('build-docs', recipients))\n"
        "asyncio.run(tell.run(folder, {'task': 'check-links', 'message': 'the README moved'}))\n"
        "print(sorted(name for name in sys.modules if name.startswith('poieo.card')))\n"
        "print((folder / 'check-links.md').read_text(encoding='utf-8').splitlines()[-1])\n"
    )
    result = _fresh(probe)
    assert result.returncode == 0, result.stderr
    modules, line = result.stdout.strip().splitlines()
    assert modules == "[]"
    assert line.endswith("task    [build-docs] the README moved"), line
