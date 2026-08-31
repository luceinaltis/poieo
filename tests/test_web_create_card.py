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


def test_a_folder_outside_the_project_is_refused(tmp_path):
    """The fence that matters. A card takes the files and shell toolsets and
    fires within seconds of being written, so without this one request starts a
    shell-capable agent anywhere on the machine -- over a port any page in the
    browser can reach. Pointing a task elsewhere is still done by hand."""
    client, cards = _client(tmp_path)
    outside = tmp_path.parent / "outside-the-project"
    outside.mkdir(exist_ok=True)

    answer = _make(client, {"name": "reach out", "folder": str(outside), "prompt": "x"})

    assert answer.status_code == 400, answer.text
    assert "outside" in answer.json()["error"]
    assert not (cards / "reach-out.yaml").exists()


def test_a_name_taken_by_another_spelling_is_refused(tmp_path):
    """`load_cards` reads .yaml, .yml and .json. Writing `x.yaml` beside an
    existing `x.yml` would leave two cards claiming one name, and the folder
    would stop loading at all -- taking every card written after it."""
    client, cards = _client(tmp_path)
    (cards / "twin.yml").write_text("name: twin\nfolder: ../work\nprompt: hi\n", encoding="utf-8")

    answer = _make(client, {"name": "twin", "folder": "../work", "prompt": "new"})

    assert answer.status_code == 409, answer.text
    assert not (cards / "twin.yaml").exists()


def test_a_project_with_no_default_models_file_is_refused(tmp_path):
    """A card written here names no binding of its own. With no default it
    would not load, and one unloadable card in a watched folder stops every
    later one from being noticed."""
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "work").mkdir()
    card(tmp_path / "cards", "own", "folder: ../work\nprompt: hi\nbinding: ../b.yaml\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("name: board\ntasks: cards\n", encoding="utf-8")
    client = TestClient(create_app(Daemon(load_config(path), store=NullStore())))

    answer = client.post("/api/projects/board/tasks", json={"name": "x", "folder": "../work", "prompt": "y"})

    assert answer.status_code == 409, answer.text
    assert not (tmp_path / "cards" / "x.yaml").exists()


def test_a_title_that_is_not_english_still_makes_a_card(tmp_path):
    """The slug kept only ASCII, so a reader writing Korean could never make a
    card at all -- every title slugged to nothing and was refused as unusable."""
    client, cards = _client(tmp_path)

    answer = _make(client, {"name": "매일 정리", "folder": "../work", "prompt": "치우기"})

    assert answer.status_code == 200, answer.text
    made = cards / f"{answer.json()['task']}.yaml"
    assert made.exists(), sorted(p.name for p in cards.iterdir())
    assert "매일 정리" in made.read_text(encoding="utf-8")


def test_a_card_can_be_made_without_being_started(tmp_path):
    """The second, quieter action beside save. Saving a card starts it within
    seconds -- a shell-capable agent over the reader's own files -- and until
    now the only way to make one and look at it first was to find the file."""
    client, cards = _client(tmp_path)
    answer = _make(client, {"name": "later", "folder": "../work", "prompt": "go", "enabled": False})

    assert answer.status_code == 200, answer.text
    assert "enabled: false" in cards.joinpath("later.yaml").read_text(encoding="utf-8")


def test_a_card_made_the_usual_way_says_nothing_about_being_enabled(tmp_path):
    """`enabled: true` says nothing a card without it does not, and the three
    fields are the whole of the short form."""
    client, cards = _client(tmp_path)
    _make(client, {"name": "now", "folder": "../work", "prompt": "go"})

    assert "enabled" not in cards.joinpath("now.yaml").read_text(encoding="utf-8")


def test_rewriting_a_card_leaves_its_switch_where_it_was(tmp_path):
    """Absent means unchanged, not on. A form that sends three fields is
    editing three fields, and defaulting to on here would have a prompt tweak
    silently start a task somebody had switched off."""
    client, cards = _client(tmp_path)
    off = client.put(
        "/api/projects/board/tasks/already",
        json={"name": "already", "folder": "../work", "prompt": "hi", "enabled": False},
    )
    assert off.status_code == 200, off.text
    assert "enabled: false" in cards.joinpath("already.yaml").read_text(encoding="utf-8")

    again = client.put(
        "/api/projects/board/tasks/already",
        json={"name": "already", "folder": "../work", "prompt": "hi again"},
    )

    assert again.status_code == 200, again.text
    text = cards.joinpath("already.yaml").read_text(encoding="utf-8")
    assert "enabled: false" in text and "hi again" in text


def test_switching_a_card_on_through_the_form_is_promised_as_live(tmp_path):
    """`enabled` is the one field the folder scan adopts whole, so the answer
    must not send the reader off for a restart they do not need."""
    client, cards = _client(tmp_path)
    client.put(
        "/api/projects/board/tasks/already",
        json={"name": "already", "folder": "../work", "prompt": "hi", "enabled": False},
    )

    answer = client.put(
        "/api/projects/board/tasks/already",
        json={"name": "already", "folder": "../work", "prompt": "hi", "enabled": True},
    )

    assert answer.status_code == 200, answer.text
    assert answer.json()["live"] is True
    assert "enabled" not in cards.joinpath("already.yaml").read_text(encoding="utf-8")
