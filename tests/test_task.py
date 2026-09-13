"""The full form of a task has a module of its own, below the daemon.

A card is the short form; ``expand`` turns it into the task the daemon and
``poieo run`` both load. That shape belongs to neither of them, and a card
reaching for it must not drag the scheduler along.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_expanding_a_card_does_not_load_the_daemon(tmp_path):
    """Making a card into a task needs the task shape, not the thing that runs it.

    A fresh interpreter, because the suite has long since imported everything;
    ``PYTHONPATH`` pins it to this checkout rather than whatever ``pip install
    -e`` last pointed at.
    """
    card = tmp_path / "chores.yaml"
    card.write_text("name: chores\nfolder: .\nprompt: tidy up\n", encoding="utf-8")
    probe = (
        "import sys\n"
        "from poieo.card import expand, load_card\n"
        f"expand(load_card({str(card)!r}))\n"
        "print(sorted(name for name in sys.modules if name.startswith('poieo.daemon')))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout


def test_the_daemon_and_the_task_module_name_one_task_shape():
    """Both spellings resolve to one class, so a task validates the same
    whichever side loaded it."""
    from poieo import daemon, task

    assert daemon.TaskSpec is task.TaskSpec
    assert daemon.TriggerSpec is task.TriggerSpec
