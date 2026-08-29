"""What the board may say about the models a project runs on.

One route, and a fence: it names the variable a credential comes from and never
the credential. `/api/tasks` still carries neither that nor an address --
see `test_the_wiring_carries_no_credentials` in test_web_server.py, which is the
other half of this pair.

Design: docs/web.md
"""

from pathlib import Path

from starlette.testclient import TestClient

from conftest import card
from poieo.daemon import Daemon, load_config
from poieo.store import NullStore
from poieo.web import create_app

_GRAPH = """\
name: quick
entry: a
nodes:
  - {id: a, type: agent, role: reader, prompt: hi}
"""

_MOCK = """\
name: models-for-a-board
providers:
  fake: {type: mock, options: {responses: {"*": "done"}}}
default: {provider: fake, model: m1}
roles:
  reader: {provider: fake, model: m2}
"""


def _client(tmp_path, *, binding=_MOCK, tasks=True, name="board"):
    """A daemon that was built but never served.

    A GET needs `daemon.projects` and nothing else, and `runners` is already
    an empty list before `serve()` fills it -- so this stays a read test
    rather than a scheduling one, over the real `LoadedProject` the route
    will actually be handed.
    """
    (tmp_path / "b.yaml").write_text(binding, encoding="utf-8")
    marker = f"name: {name}\ntasks: cards\n"
    if binding is not None:
        marker += "binding: b.yaml\n"
    if tasks:
        (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
        card(tmp_path / "cards", "f", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    else:
        (tmp_path / "cards").mkdir(exist_ok=True)
    path = tmp_path / "poieo.yaml"
    path.write_text(marker, encoding="utf-8")
    daemon = Daemon(load_config(path), store=NullStore())
    return TestClient(create_app(daemon))


def _models(client, project="board"):
    return client.get(f"/api/projects/{project}/models")


def test_the_models_report_is_what_the_binding_decided(tmp_path):
    """The same facts `poieo config` prints, so the two front ends cannot
    disagree about what this project is bound to."""
    body = _models(_client(tmp_path)).json()

    assert body["binding"]["name"] == "models-for-a-board"
    assert body["binding"]["path"].endswith("b.yaml")
    assert body["default"] == "fake/m1"
    assert body["roles"] == {"reader": "fake/m2"}
    assert body["providers"]["fake"]["type"] == "mock"


def test_the_models_report_carries_no_address(tmp_path):
    """A `base_url` is not needed to pick a model -- the endpoint's own name
    tells one from another -- and it is the one field in a binding that can
    carry a private host. Held back until something concrete needs it."""
    body = _models(_client(tmp_path)).json()

    assert "base_url" not in body["providers"]["fake"]
    assert "localhost" not in _models(_client(tmp_path)).text


def test_the_models_report_names_the_variable_and_never_its_value(tmp_path, monkeypatch):
    """The one route where a credential is a legitimate subject, and the line
    it holds instead.

    The panel has to be able to say why a model will not answer, which means
    naming the variable. So what is forbidden is the *value*, and this goes
    looking for the value rather than trusting the shape of the code.
    """
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-planted-by-this-test")
    binding = _MOCK.replace(
        "fake: {type: mock,", "fake: {type: mock, api_key_env: POIEO_TEST_KEY,"
    )
    response = _models(_client(tmp_path, binding=binding))

    assert response.json()["providers"]["fake"]["api_key_env"] == "POIEO_TEST_KEY"
    assert response.json()["providers"]["fake"]["api_key_set"] is True
    assert "sk-planted-by-this-test" not in response.text


def test_a_provider_that_names_no_variable_says_so_rather_than_unset(tmp_path):
    """`null`, not `false`: "its SDK resolves its own" is a different fact
    from "the key is missing", and a panel that showed a warning for the
    first would be crying wolf on every local endpoint."""
    body = _models(_client(tmp_path)).json()

    assert body["providers"]["fake"]["api_key_env"] is None
    assert body["providers"]["fake"]["api_key_set"] is None


def test_a_variable_that_is_not_set_reads_false(tmp_path, monkeypatch):
    monkeypatch.delenv("POIEO_TEST_KEY", raising=False)
    binding = _MOCK.replace(
        "fake: {type: mock,", "fake: {type: mock, api_key_env: POIEO_TEST_KEY,"
    )
    # No tasks, so the unset key is not a startup failure -- the panel is
    # exactly where somebody would go to find out about it.
    body = _models(_client(tmp_path, binding=binding, tasks=False)).json()

    assert body["providers"]["fake"]["api_key_set"] is False


def test_a_project_that_names_no_binding_says_so_rather_than_failing(tmp_path):
    """An answer, not an exception -- the rule the rest of this API follows."""
    (tmp_path / "cards").mkdir()
    path = tmp_path / "poieo.yaml"
    path.write_text("name: board\ntasks: cards\n", encoding="utf-8")
    client = TestClient(create_app(Daemon(load_config(path), store=NullStore())))

    response = _models(client)
    assert response.status_code == 200
    assert response.json() == {
        "binding": None,
        "providers": {},
        "default": None,
        "roles": {},
    }


def test_a_role_the_binding_cannot_resolve_says_so_rather_than_guessing(tmp_path):
    """`resolve` falls through to `default` for any role at all, so the only
    unresolvable one is in a binding with nothing to fall back on.

    Null, not absent -- `poieo config` prints `(unresolvable)` rather than
    dropping the line, and the role is in the file either way. Hiding it would
    hide the one case on this screen worth looking at.
    """
    partial = "name: half\nproviders:\n  fake: {type: mock}\nroles:\n  half: {provider: fake}\n"
    body = _models(_client(tmp_path, binding=partial, tasks=False)).json()

    assert body["default"] is None
    assert body["roles"] == {"half": None}


def test_an_unknown_project_is_404_and_names_the_ones_there_are(tmp_path):
    """The board remembers a project across restarts, so a picker holding one
    the daemon was started without is a real state, not a typo."""
    response = _models(_client(tmp_path), project="gone")

    assert response.status_code == 404
    assert "gone" in response.json()["error"]
    assert response.json()["projects"] == ["board"]


def test_the_report_reads_the_spec_the_board_is_already_painting_from(tmp_path):
    """One truth per screen.

    The panel sits beside a graph whose nodes carry a resolved model, and both
    have to come off the same in-memory spec -- so a binding re-read by a run
    moves them together rather than leaving one screen arguing with itself.
    Read from the file instead and they part company the moment anybody types
    `poieo config use`.
    """
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    card(tmp_path / "cards", "f", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("name: board\ntasks: cards\nbinding: b.yaml\n", encoding="utf-8")
    daemon = Daemon(load_config(path), store=NullStore())
    client = TestClient(create_app(daemon))

    # Move the file underneath, without telling the daemon. The report must
    # still say what the daemon would really run, which is the old spec.
    (tmp_path / "b.yaml").write_text(
        _MOCK.replace("model: m2", "model: moved"), encoding="utf-8"
    )
    body = _models(client).json()

    loaded = daemon.projects[0].tasks[0].binding
    assert body["roles"]["reader"] == loaded.resolve("reader").ref == "fake/m2"
    assert Path(body["binding"]["path"]).name == "b.yaml"
