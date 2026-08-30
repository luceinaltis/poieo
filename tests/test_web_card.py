"""Reading a task's card back, and rewriting it, from the board.

The rewrite is the fifth kind of write growing a second verb, not a sixth
kind: the fence is the one `make` built -- one card, in this project's tasks
folder, and nothing else -- and rewriting a card that exists sits inside it
exactly as making one did. The GET beside it is what an editor opens with,
and what "make one like it" prefills from.

The daemon's own re-read rules stay the judge of what an edit means: a new
prompt is picked up by the next run, while a change to the folder, the
schedule or the isolation only takes effect on a restart -- so the answer
says which of the two the caller just did, and the board can warn instead of
letting a person believe an ignored edit took.

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

_CARD = "name: Already\nfolder: ../work\nprompt: keep things tidy\n"


def _client(tmp_path):
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "work").mkdir(exist_ok=True)
    card(tmp_path / "cards", "already", _CARD)
    path = tmp_path / "poieo.yaml"
    path.write_text("name: board\nbinding: b.yaml\ntasks: cards\n", encoding="utf-8")
    daemon = Daemon(load_config(path), store=NullStore())
    return TestClient(create_app(daemon)), tmp_path / "cards"


def _get(client, task="already", project="board"):
    return client.get(f"/api/projects/{project}/tasks/{task}")


def _put(client, text, task="already", project="board"):
    return client.put(f"/api/projects/{project}/tasks/{task}", json={"text": text})


def test_the_card_reads_back_as_the_file_and_as_its_three_fields(tmp_path):
    """The text is what an editor opens; the fields are what a prefill wants.
    Both, because parsing YAML in the page would be a second parser to keep
    honest against this one."""
    client, cards = _client(tmp_path)
    answer = _get(client)

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["task"] == "already"
    assert body["text"] == (cards / "already.yaml").read_text(encoding="utf-8")
    assert body["name"] == "Already"
    assert body["folder"] == "../work"
    assert body["prompt"] == "keep things tidy"


def test_a_task_the_daemon_does_not_know_is_a_404_both_ways(tmp_path):
    client, cards = _client(tmp_path)
    assert _get(client, task="ghost").status_code == 404
    assert _put(client, _CARD, task="ghost").status_code == 404
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


def test_a_new_prompt_lands_in_the_file_and_is_live(tmp_path):
    """The edit the whole feature exists for: fix the wording, and the next
    run reads it. `live` is how the board knows not to warn."""
    client, cards = _client(tmp_path)
    text = "name: Already\nfolder: ../work\nprompt: sharper words\n"
    answer = _put(client, text)

    assert answer.status_code == 200, answer.text
    assert answer.json() == {"ok": True, "task": "already", "live": True}
    assert (cards / "already.yaml").read_text(encoding="utf-8") == text


def test_a_changed_folder_is_written_but_says_it_waits_for_a_restart(tmp_path):
    """The daemon refuses to half-adopt a card whose spec changed -- shell
    outside the isolation it asked for is the failure -- so the write goes
    through and the answer says the truth: not until a restart."""
    client, cards = _client(tmp_path)
    (tmp_path / "work2").mkdir()
    text = "name: Already\nfolder: ../work2\nprompt: keep things tidy\n"
    answer = _put(client, text)

    assert answer.status_code == 200, answer.text
    assert answer.json() == {"ok": True, "task": "already", "live": False}
    assert (cards / "already.yaml").read_text(encoding="utf-8") == text


def test_a_folder_outside_the_project_is_refused_and_nothing_changes(tmp_path):
    """Same fence as making a card, for the same reason: one request must not
    point a shell-capable task anywhere on the machine."""
    client, cards = _client(tmp_path)
    outside = tmp_path.parent
    before = (cards / "already.yaml").read_text(encoding="utf-8")
    answer = _put(client, f"name: Already\nfolder: {outside}\nprompt: x\n")

    assert answer.status_code == 400, answer.text
    assert (cards / "already.yaml").read_text(encoding="utf-8") == before


def test_a_folder_that_is_not_there_is_refused(tmp_path):
    client, cards = _client(tmp_path)
    before = (cards / "already.yaml").read_text(encoding="utf-8")
    answer = _put(client, "name: Already\nfolder: ../gone\nprompt: x\n")

    assert answer.status_code == 400, answer.text
    assert (cards / "already.yaml").read_text(encoding="utf-8") == before


def test_text_that_is_not_a_card_is_refused_whole(tmp_path):
    """A graph, broken YAML, an empty page: each would be a card the daemon
    warns about every five seconds, saved by the button meant to fix one."""
    client, cards = _client(tmp_path)
    before = (cards / "already.yaml").read_text(encoding="utf-8")
    for text in (
        "nodes:\n  - {id: a, type: agent}\n",  # a graph, not a card
        "name: [broken\n",  # not YAML at all
        "",  # nothing
        "just words\n",  # YAML, but not a mapping
    ):
        answer = _put(client, text)
        assert answer.status_code == 400, (text, answer.text)
    assert (cards / "already.yaml").read_text(encoding="utf-8") == before


def test_a_refusal_leaves_no_scratch_file_behind(tmp_path):
    """Validation needs a file the loader would accept, but the daemon watches
    this folder: anything left behind becomes a task."""
    client, cards = _client(tmp_path)
    _put(client, "name: [broken\n")
    _put(client, "name: Already\nfolder: ../gone\nprompt: x\n")
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


def test_the_rewrite_cannot_rename_the_task(tmp_path):
    """Identity is the filename. A new `name:` inside is a new title on the
    same card, and no second file appears."""
    client, cards = _client(tmp_path)
    answer = _put(client, "name: A Better Title\nfolder: ../work\nprompt: keep things tidy\n")

    assert answer.status_code == 200, answer.text
    assert answer.json()["task"] == "already"
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


def test_a_graph_naming_rewrite_is_fenced_exactly_like_a_folder(tmp_path):
    """The fence forgot one shape: a card may name a graph instead of a
    prompt, and a graph needs no folder -- so a rewrite that flipped the shape
    walked out of the project with nothing checking it. The graph's path takes
    the same refusals the folder does: inside this project, and it has to be
    there."""
    client, cards = _client(tmp_path)
    before = (cards / "already.yaml").read_text(encoding="utf-8")

    outside = tmp_path.parent / "evil.yaml"
    outside.write_text("nodes:\n  - {id: a, type: agent, prompt: hi}\n", encoding="utf-8")
    for graph in (str(outside), "../../evil.yaml", "../gone.yaml"):
        answer = _put(client, f"name: Already\ngraph: {graph}\n")
        assert answer.status_code == 400, (graph, answer.text)
    assert (cards / "already.yaml").read_text(encoding="utf-8") == before

    # ...and one inside the project is not caught in the same net.
    (cards / "steps.yaml").write_text("name: steps\nnodes:\n  - {id: a, type: agent, prompt: hi}\n", encoding="utf-8")
    answer = _put(client, "name: Already\ngraph: steps.yaml\n")
    assert answer.status_code == 200, answer.text


def test_live_is_measured_against_what_the_daemon_runs_not_the_file(tmp_path):
    """After a structural edit the file is ahead of the daemon, which adopts
    nothing until a restart. A prompt tweak on top of that must not say
    `live` -- the daemon compares against its own memory, and so does this."""
    client, cards = _client(tmp_path)
    (tmp_path / "work2").mkdir()

    first = _put(client, "name: Already\nfolder: ../work2\nprompt: keep things tidy\n")
    assert first.json()["live"] is False

    second = _put(client, "name: Already\nfolder: ../work2\nprompt: sharper words\n")
    assert second.status_code == 200, second.text
    # The file only differs from the file by a prompt, but the daemon is
    # still running ../work -- nothing here is live until a restart.
    assert second.json()["live"] is False


def test_two_saves_in_a_row_both_land_and_the_last_one_wins(tmp_path):
    client, cards = _client(tmp_path)
    a = _put(client, "name: Already\nfolder: ../work\nprompt: first\n")
    b = _put(client, "name: Already\nfolder: ../work\nprompt: second\n")
    assert a.status_code == 200 and b.status_code == 200
    assert "second" in (cards / "already.yaml").read_text(encoding="utf-8")
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml", "steps.yaml"] or sorted(
        p.name for p in cards.iterdir()
    ) == ["already.yaml"]
