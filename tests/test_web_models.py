"""Every model this project can reach, endpoint by endpoint.

Asked live, for the reason `poieo config models` is asked live. And a fence:
the report names the variable a credential comes from and never the
credential. `/api/tasks` still carries neither that nor an address -- see
`test_the_wiring_carries_no_credentials` in test_web_server.py, the other half
of this pair.

Design: docs/web.md
"""

from starlette.testclient import TestClient

from conftest import card
from poieo import detect as detect_module
from poieo.daemon import Daemon, load_config
from poieo.detect import Served
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

# What one endpoint answers with, keyed by the type asked. Nothing here reaches
# a socket: the route's whole job is to ask, so the asking is what is stubbed.
CATALOGUE = {
    "mock": (),
    "ollama": (
        Served(
            id="qwen3.5:latest",
            context=262144,
            size="9.0B",
            quantization="Q4_K_M",
            capabilities=("completion", "vision"),
        ),
    ),
    "openai_compatible": (
        Served(id="qwen/flash", context=1000000, price=(0.15, 0.47)),
    ),
}


def _asks(monkeypatch, catalogue=None):
    served = CATALOGUE if catalogue is None else catalogue

    async def fake(type_, base_url=None, limit=None):
        # The route lifts the cap; a stub that refused the argument would let
        # that go untested.
        assert limit is None, "the catalogue panel must not be capped"
        return served.get(type_, ())

    monkeypatch.setattr(detect_module, "catalogue_for", fake)


def _client(tmp_path, *, binding=_MOCK, tasks=True, name="board"):
    """A daemon that was built but never served.

    A GET needs `daemon.projects` and nothing else, and `runners` is already an
    empty list before `serve()` fills it -- so this stays a read test rather
    than a scheduling one, over the real `LoadedProject` the route is handed.
    """
    (tmp_path / "b.yaml").write_text(binding, encoding="utf-8")
    marker = f"name: {name}\ntasks: cards\nbinding: b.yaml\n"
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


def _endpoints(body):
    return {e["name"]: e for e in body["endpoints"]}


_TWO = """\
name: two
providers:
  local: {type: ollama, base_url: "http://localhost:11434"}
  routed: {type: openai_compatible, base_url: "http://x/v1"}
default: {provider: local, model: "qwen3.5:latest"}
"""

# The same two, with the routed one at an address that has a name.
_ROUTED = _TWO.replace("http://x/v1", "https://openrouter.ai/api/v1")


def test_every_declared_endpoint_is_listed_with_what_it_serves(tmp_path, monkeypatch):
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_TWO)).json()

    assert [e["name"] for e in body["endpoints"]] == ["local", "routed"]
    assert [m["id"] for m in _endpoints(body)["local"]["models"]] == ["qwen3.5:latest"]


def test_a_local_model_carries_what_it_costs_in_memory_and_no_price(tmp_path, monkeypatch):
    """Ollama charges nothing per token, so there is no price to report. What a
    local model costs is the size and quantization it does report."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_TWO)).json()

    model = _endpoints(body)["local"]["models"][0]
    assert (model["size"], model["quantization"]) == ("9.0B", "Q4_K_M")
    assert model["context"] == 262144
    assert model["capabilities"] == ["completion", "vision"]
    assert model["price"] is None


def test_a_published_price_crosses_as_input_and_output(tmp_path, monkeypatch):
    """From the endpoint's own listing, never from a table in this repository."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_TWO)).json()

    assert _endpoints(body)["routed"]["models"][0]["price"] == {
        "input": 0.15,
        "output": 0.47,
    }


def test_the_model_in_use_says_which_roles_are_on_it(tmp_path, monkeypatch):
    """What a reader is using, among what they could be. A model may serve
    more than one role, so this is a list and not a flag."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_TWO)).json()

    model = _endpoints(body)["local"]["models"][0]
    assert model["ref"] == "local/qwen3.5:latest"
    assert model["used_by"] == ["default"]
    assert _endpoints(body)["routed"]["models"][0]["used_by"] == []


def test_an_endpoint_that_cannot_be_asked_says_so_rather_than_reading_as_down(
    tmp_path, monkeypatch
):
    """`mock` answers from the binding file itself. Silence from it is a
    different fact from an endpoint that did not answer."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path)).json()

    assert _endpoints(body)["fake"]["askable"] is False
    assert _endpoints(body)["fake"]["models"] == []


def test_a_listing_says_whether_it_is_what_is_here_or_what_is_offered(
    tmp_path, monkeypatch
):
    """Two listings that look identical and mean different things. Ollama's is
    `ollama list` -- pulled onto this disk, ready now. A routed endpoint's is a
    catalogue of what it would run for money, with nothing here yet. A panel
    that drew both the same way would have a reader believe four hundred models
    were sitting on their laptop."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_TWO)).json()

    assert _endpoints(body)["local"]["installed"] is True
    assert _endpoints(body)["routed"]["installed"] is False


def test_an_endpoint_is_named_by_something_a_person_recognises(tmp_path, monkeypatch):
    """`openai_compatible` is vLLM and SGLang and LM Studio and llama.cpp and
    every hosted router at once. The address says which, and it is the address
    -- not the label it produces -- that must not cross."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_ROUTED)).json()

    assert _endpoints(body)["local"]["label"] == "Ollama"
    assert _endpoints(body)["routed"]["label"] == "OpenRouter"


def test_an_address_nobody_wrote_down_leaves_the_label_null(tmp_path, monkeypatch):
    """The panel falls back to the type, which is what it says today. Guessing
    would be worse than the fallback."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_TWO)).json()

    assert _endpoints(body)["routed"]["label"] is None


def test_the_report_carries_no_address(tmp_path, monkeypatch):
    """A `base_url` is not needed to pick a model -- the endpoint's own name
    tells one from another -- and it is the one binding field that can carry a
    private host."""
    _asks(monkeypatch)
    response = _models(_client(tmp_path, binding=_TWO))

    assert "base_url" not in response.text
    assert "localhost" not in response.text


def test_the_report_names_the_variable_and_never_its_value(tmp_path, monkeypatch):
    """The one route where a credential is a legitimate subject, and the line
    it holds instead.

    An endpoint whose key is missing lists nothing, and the panel has to be
    able to say why -- which means naming the variable. So what is forbidden
    is the *value*, and this goes looking for the value rather than trusting
    the shape of the code.
    """
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-planted-by-this-test")
    _asks(monkeypatch)
    binding = _MOCK.replace(
        "fake: {type: mock,", "fake: {type: mock, api_key_env: POIEO_TEST_KEY,"
    )
    response = _models(_client(tmp_path, binding=binding))

    assert _endpoints(response.json())["fake"]["api_key_env"] == "POIEO_TEST_KEY"
    assert _endpoints(response.json())["fake"]["api_key_set"] is True
    assert "sk-planted-by-this-test" not in response.text


def test_an_endpoint_that_names_no_variable_says_null_rather_than_unset(
    tmp_path, monkeypatch
):
    """`null`, not `false`: "its SDK resolves its own" is a different fact from
    "the key is missing", and a panel warning about the first would cry wolf on
    every local endpoint."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path)).json()

    assert _endpoints(body)["fake"]["api_key_env"] is None
    assert _endpoints(body)["fake"]["api_key_set"] is None


def test_a_variable_that_is_not_set_reads_false(tmp_path, monkeypatch):
    monkeypatch.delenv("POIEO_TEST_KEY", raising=False)
    _asks(monkeypatch)
    binding = _MOCK.replace(
        "fake: {type: mock,", "fake: {type: mock, api_key_env: POIEO_TEST_KEY,"
    )
    # No tasks, so an unset key is not a startup failure -- and the panel is
    # exactly where somebody would go to find out about it.
    body = _models(_client(tmp_path, binding=binding, tasks=False)).json()

    assert _endpoints(body)["fake"]["api_key_set"] is False


def test_every_endpoint_is_asked_at_once(tmp_path, monkeypatch):
    """Each endpoint costs up to `HTTP_TIMEOUT` when it is not listening. Asked
    one at a time, a panel over two dead endpoints waits for both in turn;
    asked together it waits for the slower one. Measured the way the board's
    own review states are: by how many were ever in flight together."""
    import asyncio as _asyncio

    active = 0
    peak = 0
    asked: list[str] = []

    async def fake(type_, base_url=None, limit=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        asked.append(type_)
        await _asyncio.sleep(0.01)  # a real await point, so the other can start
        active -= 1
        return ()

    monkeypatch.setattr(detect_module, "catalogue_for", fake)
    _models(_client(tmp_path, binding=_TWO))

    assert sorted(asked) == ["ollama", "openai_compatible"]
    assert peak == 2


def test_a_project_that_names_no_binding_says_so_rather_than_failing(tmp_path):
    """An answer, not an exception -- the rule the rest of this API follows."""
    (tmp_path / "cards").mkdir()
    path = tmp_path / "poieo.yaml"
    path.write_text("name: board\ntasks: cards\n", encoding="utf-8")
    client = TestClient(create_app(Daemon(load_config(path), store=NullStore())))

    response = _models(client)
    assert response.status_code == 200
    assert response.json() == {"binding": None, "endpoints": []}


def test_an_unknown_project_is_404_and_names_the_ones_there_are(tmp_path, monkeypatch):
    """The board remembers a project across restarts, so a picker holding one
    the daemon was started without is a real state, not a typo."""
    _asks(monkeypatch)
    response = _models(_client(tmp_path), project="gone")

    assert response.status_code == 404
    assert "gone" in response.json()["error"]
    assert response.json()["projects"] == ["board"]


def test_the_report_names_the_file_these_endpoints_came_from(tmp_path, monkeypatch):
    """Provenance, not configuration: where to go when one of them is wrong."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path)).json()

    assert body["binding"]["name"] == "models-for-a-board"
    assert body["binding"]["path"].endswith("b.yaml")
