"""What survives `poieo eject`.

Ejecting expands a card into the graph it stood for and rewrites the card to
name it. Only the node keys -- prompt, role, tools, max_turns, deadline -- move
into the graph; everything else describes the *task* and has to come back out
the other side. It did not: a card's schedule, its input and its handoffs were
silently dropped, so ejecting a scheduled task stopped it running.
"""

import yaml
from typer.testing import CliRunner

from poieo.card import load_card
from poieo.cli import app

runner = CliRunner()


def _task(tmp_path, body):
    (tmp_path / "project").mkdir(exist_ok=True)
    (tmp_path / "tasks").mkdir(exist_ok=True)
    path = tmp_path / "tasks" / "tidy.yaml"
    path.write_text(f"folder: {(tmp_path / 'project').as_posix()}\n{body}", encoding="utf-8")
    return path


def test_eject_keeps_the_schedule_the_input_and_the_handoffs(tmp_path):
    path = _task(
        tmp_path,
        """name: tidy the project
prompt: go
trigger:
  type: interval
  every: 10m
  run_at_start: true
input:
  journal: yesterday
  depth: 3
input_file: notes.json
then:
  - when: "'RED' in summary"
    to: mend
    label: red
on_error: stop
""",
    )

    result = runner.invoke(app, ["eject", str(path)])
    assert result.exit_code == 0, result.output

    rewritten = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert rewritten["graph"] == "tidy.graph.yaml"
    assert rewritten["trigger"] == {"type": "interval", "every": "10m", "run_at_start": True}
    assert rewritten["input"] == {"journal": "yesterday", "depth": 3}
    assert rewritten["input_file"] == "notes.json"
    assert rewritten["then"] == [{"when": "'RED' in summary", "to": "mend", "label": "red"}]
    assert rewritten["on_error"] == "stop"

    # ...and it still loads, so what came back is a card and not just text.
    after = load_card(path)
    assert after.trigger == {"type": "interval", "every": "10m", "run_at_start": True}
    assert [(b.when, b.to, b.label) for b in after.then] == [("'RED' in summary", "mend", "red")]
    assert after.on_error == "stop"


def test_eject_leaves_out_what_the_card_never_said(tmp_path):
    """A card that set none of them keeps a rewrite free of empty keys."""
    path = _task(tmp_path, "name: tidy the project\nprompt: go\n")
    assert runner.invoke(app, ["eject", str(path)]).exit_code == 0

    rewritten = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("trigger", "input", "input_file", "then", "on_error"):
        assert key not in rewritten
