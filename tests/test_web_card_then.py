"""Connecting one task to the next, from the board.

A card's `then:` is the wiring between tasks: when a run of this one ends,
which task starts next and on what condition. Until the board could write it,
the only way to connect two cards was to open the file -- and the board drew
the wires it could not draw.

A third spelling of the same rewrite, not a new write: the daemon splices the
new `then:` into the file's own text, so a comment or a field the form cannot
show survives, and the result goes through the same judge every rewrite does.

Design: docs/web.md
"""

import json

from conftest import card
from starlette.testclient import TestClient

from poieo.daemon import Daemon, load_config
from poieo.store import NullStore
from poieo.web import create_app

_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "done"}}}
default: {provider: fake, model: m1}
"""

_WATCH = """\
# Looks, and says RED or GREEN.
folder: ../work
prompt: run the suite
then:
  # read what the step said
  - when: "'RED' in summary"
    to: mend
    label: red
every: 10m
"""


def _client(tmp_path, body=_WATCH):
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "work").mkdir(exist_ok=True)
    card(tmp_path / "cards", "watch", body)
    card(tmp_path / "cards", "mend", "folder: ../work\nprompt: fix it\ntrigger: {type: manual}\n")
    card(tmp_path / "cards", "tell", "folder: ../work\nprompt: say so\ntrigger: {type: manual}\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("name: board\nbinding: b.yaml\ntasks: cards\n", encoding="utf-8")
    daemon = Daemon(load_config(path), store=NullStore())
    return TestClient(create_app(daemon)), tmp_path / "cards"


def _connect(client, then, task="watch"):
    return client.put(f"/api/projects/board/tasks/{task}", json={"then": then})


def test_the_card_reads_back_its_connections_with_their_conditions(tmp_path):
    """The listing draws an arrow as where it goes and its word; an editor
    also needs the condition, to show it and to send it back unchanged."""
    client, _ = _client(tmp_path)
    answer = client.get("/api/projects/board/tasks/watch")

    assert answer.status_code == 200, answer.text
    assert answer.json()["then"] == [{"when": "'RED' in summary", "to": "mend", "label": "red"}]


def test_a_new_connection_lands_and_the_rest_of_the_file_is_kept(tmp_path):
    """The comment on top and the schedule under the block are the file's own
    bytes; a connection made on the board must not cost them."""
    client, cards = _client(tmp_path)
    then = [
        {"when": "'RED' in summary", "to": "mend", "label": "red"},
        {"when": "true", "to": "tell"},
    ]
    answer = _connect(client, then)

    assert answer.status_code == 200, answer.text
    assert answer.json()["ok"] is True
    text = (cards / "watch.yaml").read_text(encoding="utf-8")
    assert text.startswith("name: watch\n# Looks, and says RED or GREEN.\nfolder: ../work\n")
    assert text.endswith("every: 10m\n")
    assert client.get("/api/projects/board/tasks/watch").json()["then"] == [
        {"when": "'RED' in summary", "to": "mend", "label": "red"},
        {"when": "true", "to": "tell", "label": None},
    ]


def test_a_connection_is_live_not_waiting_for_a_restart(tmp_path):
    """Only read when a run ends, so nothing built at startup has to change:
    the answer must not tell the board it waits for a restart."""
    client, _ = _client(tmp_path)
    answer = _connect(client, [{"when": "true", "to": "tell"}])

    assert answer.status_code == 200, answer.text
    assert answer.json()["live"] is True


def test_the_first_connection_is_added_to_a_card_that_had_none(tmp_path):
    client, cards = _client(tmp_path, "folder: ../work\nprompt: run the suite\n")
    answer = _connect(client, [{"when": "true", "to": "mend"}])

    assert answer.status_code == 200, answer.text
    text = (cards / "watch.yaml").read_text(encoding="utf-8")
    assert text.startswith("name: watch\nfolder: ../work\nprompt: run the suite\n")
    assert client.get("/api/projects/board/tasks/watch").json()["then"] == [
        {"when": "true", "to": "mend", "label": None}
    ]


def test_taking_the_last_connection_away_removes_the_block(tmp_path):
    client, cards = _client(tmp_path)
    answer = _connect(client, [])

    assert answer.status_code == 200, answer.text
    text = (cards / "watch.yaml").read_text(encoding="utf-8")
    assert "then" not in text
    assert "mend" not in text
    assert text.endswith("every: 10m\n")


def test_a_task_the_project_does_not_have_is_refused_and_nothing_changes(tmp_path):
    """A handoff to a name nobody answers to is dropped at run time with a
    log line; the board can say so before anything is written."""
    client, cards = _client(tmp_path)
    before = (cards / "watch.yaml").read_text(encoding="utf-8")
    answer = _connect(client, [{"when": "true", "to": "ghost"}])

    assert answer.status_code == 400, answer.text
    assert "ghost" in answer.json()["error"]
    assert (cards / "watch.yaml").read_text(encoding="utf-8") == before


def test_a_condition_that_does_not_parse_is_refused_and_nothing_changes(tmp_path):
    client, cards = _client(tmp_path)
    before = (cards / "watch.yaml").read_text(encoding="utf-8")
    answer = _connect(client, [{"when": "__import__('os')", "to": "mend"}])

    assert answer.status_code == 400, answer.text
    assert (cards / "watch.yaml").read_text(encoding="utf-8") == before


def test_a_connection_that_is_not_a_list_of_arrows_is_refused(tmp_path):
    client, cards = _client(tmp_path)
    before = (cards / "watch.yaml").read_text(encoding="utf-8")

    assert _connect(client, "mend").status_code == 400
    assert _connect(client, [{"to": "mend"}]).status_code == 400
    assert (cards / "watch.yaml").read_text(encoding="utf-8") == before


def test_a_json_card_is_connected_too(tmp_path):
    """A card may be JSON, which has no comments to keep: rewritten whole."""
    _, cards = _client(tmp_path)
    (cards / "watch.yaml").unlink()
    (cards / "watch.json").write_text(
        json.dumps({"name": "watch", "folder": "../work", "prompt": "run the suite"}), encoding="utf-8"
    )
    client = TestClient(create_app(Daemon(load_config(tmp_path / "poieo.yaml"), store=NullStore())))
    answer = _connect(client, [{"when": "true", "to": "mend"}])

    assert answer.status_code == 200, answer.text
    data = json.loads((cards / "watch.json").read_text(encoding="utf-8"))
    assert data["then"] == [{"when": "true", "to": "mend"}]
    assert data["prompt"] == "run the suite"
