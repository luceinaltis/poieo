"""Writing a task card from the board.

The **fifth kind** of write here: it makes a file that did not exist, in the
folder the daemon watches, and a card that appears there starts running. Its
own fence is that it may write one card into the project's tasks folder and
nothing else -- not a graph, not a binding, and never outside that folder.

DESIGN.md asks for three things and no more: a name, the folder it works in,
and its prompt. The folder stays explicit on purpose -- it is the one thing the
model's hands will touch, and a default there would fill in the one moment the
user is meant to see.

Design: docs/web.md
"""

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


def _client(tmp_path, *, name="board"):
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "work").mkdir(exist_ok=True)
    card(tmp_path / "cards", "already", "folder: ../work\nprompt: hi\n")
    path = tmp_path / "poieo.yaml"
    path.write_text(f"name: {name}\nbinding: b.yaml\ntasks: cards\n", encoding="utf-8")
    daemon = Daemon(load_config(path), store=NullStore())
    return TestClient(create_app(daemon)), tmp_path / "cards"


def _make(client, body, project="board"):
    return client.post(f"/api/projects/{project}/tasks", json=body)


def test_a_card_is_written_where_the_daemon_will_find_it(tmp_path):
    """Name, folder, prompt. Saved, and that is the whole registration."""
    client, cards = _client(tmp_path)
    answer = _make(client, {"name": "tidy up", "folder": "../work", "prompt": "look around"})

    assert answer.status_code == 200, answer.text
    written = cards / "tidy-up.yaml"
    assert written.exists(), sorted(p.name for p in cards.iterdir())
    text = written.read_text(encoding="utf-8")
    assert "tidy up" in text and "look around" in text and "../work" in text
    # The board has to be able to name it afterwards, and a task's identity is
    # its filename rather than the title it was given.
    assert answer.json()["task"] == "tidy-up"


def test_a_folder_that_is_not_there_is_refused_and_nothing_is_written(tmp_path):
    """The folder is the one thing the model's hands will touch. A card naming
    one that does not exist would fail at 3am, which is the hour this project
    exists to keep quiet."""
    client, cards = _client(tmp_path)
    answer = _make(client, {"name": "nowhere", "folder": "../gone", "prompt": "x"})

    assert answer.status_code == 400, answer.text
    assert not (cards / "nowhere.yaml").exists()


def test_a_name_already_taken_is_refused(tmp_path):
    """Two cards in one folder cannot share a filename, and the filename is
    the task's identity -- so this is a name collision, not a file one."""
    client, cards = _client(tmp_path)
    before = (cards / "already.yaml").read_text(encoding="utf-8")

    answer = _make(client, {"name": "already", "folder": "../work", "prompt": "new words"})

    assert answer.status_code == 409, answer.text
    assert (cards / "already.yaml").read_text(encoding="utf-8") == before


def test_a_name_that_leaves_the_folder_is_refused(tmp_path):
    """The fence: one card, in the tasks folder. A name is turned into a
    filename, so it is the place a path would get in."""
    client, cards = _client(tmp_path)
    for attempt in ("../escape", "..", "/etc/passwd", ""):
        answer = _make(client, {"name": attempt, "folder": "../work", "prompt": "x"})
        assert answer.status_code == 400, (attempt, answer.text)
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


def test_a_card_with_nothing_to_do_is_refused(tmp_path):
    """A prompt is one of the three things DESIGN.md says a task cannot do
    without. An empty one is a card that would run and ask for nothing."""
    client, cards = _client(tmp_path)
    answer = _make(client, {"name": "empty", "folder": "../work", "prompt": "   "})

    assert answer.status_code == 400, answer.text
    assert not (cards / "empty.yaml").exists()
