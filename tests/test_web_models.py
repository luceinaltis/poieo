"""Every model this project can reach, endpoint by endpoint.

Asked live, for the reason `poieo config models` is asked live. And a fence:
the report names the variable a credential comes from and never the
credential. `/api/tasks` still carries neither that nor an address -- see
`test_the_wiring_carries_no_credentials` in test_web_server.py, the other half
of this pair.

Design: docs/web.md
"""

import asyncio
import os
from dataclasses import replace

import httpx
from conftest import card
from starlette.testclient import TestClient

from poieo import detect as detect_module
from poieo.daemon import Daemon, load_config
from poieo.detect import Catalogue, Served
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
    "mock": Catalogue(),
    "ollama": Catalogue(
        (
            Served(
                id="qwen3.5:latest",
                context=262144,
                size="9.0B",
                quantization="Q4_K_M",
                capabilities=("completion", "vision"),
            ),
        )
    ),
    "openai_compatible": Catalogue((Served(id="qwen/flash", context=1000000, price=(0.15, 0.47)),)),
}


def _asks(monkeypatch, catalogue=None):
    served = CATALOGUE if catalogue is None else catalogue

    async def fake(type_, base_url=None, limit=None, api_key_env=None):
        # The route lifts the cap; a stub that refused the argument would let
        # that go untested.
        assert limit is None, "the catalogue panel must not be capped"
        return served.get(type_, Catalogue())

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

# Block form, which is what `poieo init` writes and the only shape `rebind`
# will edit -- the flow style above is legal, rare, and exactly where guessing
# corrupts a config, so it refuses instead. Written out here because a test
# that expects a write has to be given a file that can be written to.
_BLOCK = """name: block
providers:
  local:
    type: ollama
    base_url: http://localhost:11434
default:
  provider: local
  model: "qwen3.5:latest"
roles:
  reader:
    provider: local
    model: "qwen3.5:latest"
"""


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


def test_an_endpoint_that_cannot_be_asked_says_so_rather_than_reading_as_down(tmp_path, monkeypatch):
    """`mock` answers from the binding file itself. Silence from it is a
    different fact from an endpoint that did not answer."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path)).json()

    assert _endpoints(body)["fake"]["askable"] is False
    assert _endpoints(body)["fake"]["models"] == []


def test_a_listing_says_whether_it_is_what_is_here_or_what_is_offered(tmp_path, monkeypatch):
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


def test_the_report_names_the_host_but_not_the_whole_address(tmp_path, monkeypatch):
    """Which machine, and nothing more of the address.

    This used to withhold the address entirely, on the argument that an
    endpoint's own name tells one from another. It does not: `poieo config`
    writes the key `ollama` for an Ollama wherever it runs, so a project with
    one on this laptop and one on an office server had two endpoints a reader
    could not tell apart -- and the panel told them both were on this machine.
    docs/web.md said the argument for letting an address through would have to
    be concrete. That is the concrete one.

    Host and port, because that is what identifies a machine. The scheme and
    the path are not part of the answer and do not cross.
    """
    _asks(monkeypatch)
    response = _models(_client(tmp_path, binding=_TWO))

    assert _endpoints(response.json())["local"]["host"] == "localhost:11434"
    assert "base_url" not in response.text
    assert "http://" not in response.text


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
    binding = _MOCK.replace("fake: {type: mock,", "fake: {type: mock, api_key_env: POIEO_TEST_KEY,")
    response = _models(_client(tmp_path, binding=binding))

    assert _endpoints(response.json())["fake"]["api_key_env"] == "POIEO_TEST_KEY"
    assert _endpoints(response.json())["fake"]["api_key_set"] is True
    assert "sk-planted-by-this-test" not in response.text


def _keyed(monkeypatch, wants: str, served: Catalogue):
    """A catalogue that answers only when asked with the right key variable.

    What a hosted endpoint does: an unauthenticated listing is a 401, which
    detection reads as an endpoint serving nothing at all.
    """

    async def fake(type_, base_url=None, limit=None, api_key_env=None):
        return served if api_key_env == wants else Catalogue()

    monkeypatch.setattr(detect_module, "catalogue_for", fake)


def test_a_keyed_endpoint_is_asked_with_the_variable_the_binding_names(tmp_path, monkeypatch):
    """The panel is the first place a hosted endpoint shows up, and it asked
    without the key -- so an endpoint that was working perfectly reported an
    empty list, next to a green `api_key_set`."""
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-real")
    _keyed(monkeypatch, "POIEO_TEST_KEY", Catalogue((Served(id="m1"), Served(id="m2"))))
    binding = _MOCK.replace("fake: {type: mock,", "fake: {type: mock, api_key_env: POIEO_TEST_KEY,")

    body = _models(_client(tmp_path, binding=binding)).json()

    assert [m["id"] for m in _endpoints(body)["fake"]["models"]] == ["m1", "m2"]


def test_an_endpoint_that_names_no_variable_says_null_rather_than_unset(tmp_path, monkeypatch):
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
    binding = _MOCK.replace("fake: {type: mock,", "fake: {type: mock, api_key_env: POIEO_TEST_KEY,")
    # No tasks, so an unset key is not a startup failure -- and the panel is
    # exactly where somebody would go to find out about it.
    body = _models(_client(tmp_path, binding=binding, tasks=False)).json()

    assert _endpoints(body)["fake"]["api_key_set"] is False


def test_every_endpoint_is_asked_at_once(tmp_path, monkeypatch):
    """Each address costs up to `HTTP_TIMEOUT` when nothing is listening. Asked
    one at a time, a panel over two dead endpoints waits for both in turn;
    asked together it waits for the slower one. Measured the way the board's
    own review states are: by how many were ever in flight together.

    Only the declared ones. Looking for engines this project has *not* got is
    the route below, and the reason it is a separate route: a candidate port
    nothing is listening on costs a whole timeout, so folding the search in
    here would have made every catalogue wait on its own footnote.
    """
    import asyncio as _asyncio

    active = 0
    peak = 0
    asked: list[str] = []

    async def fake(type_, base_url=None, limit=None, api_key_env=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        asked.append(type_)
        await _asyncio.sleep(0.01)  # a real await point, so the other can start
        active -= 1
        return Catalogue()

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


# -- pointing a role at another model ---------------------------------------
#
# The one write here, and the fourth kind of route in this API: it edits a file
# the reader keeps, which is not the review, and its effect outlives the
# process, which is not control. Every refusal below is checked *before*
# `rebind` opens the file, so a request that will be refused never touches it.


def _use(client, target, role=None, project="board"):
    body = {"target": target}
    if role is not None:
        body["role"] = role
    return client.post(f"/api/projects/{project}/models/use", json=body)


def test_using_a_model_points_the_default_at_it(tmp_path, monkeypatch):
    _asks(monkeypatch, {"ollama": Catalogue((Served(id="llama3.2:3b"),))})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _use(client, "local/llama3.2:3b")

    assert reply.status_code == 200
    assert reply.json() == {
        "status": "using",
        "role": "default",
        "ref": "local/llama3.2:3b",
        "checked": True,
        "adopted": True,
    }
    text = (tmp_path / "b.yaml").read_text(encoding="utf-8")
    assert "llama3.2:3b" in text
    # Comments and every other line survive: this is text surgery on the two
    # lines it came for, not a parse and a dump.
    assert "base_url: http://localhost:11434" in text


def test_a_keyed_endpoint_is_asked_with_its_key_before_a_model_is_believed(tmp_path, monkeypatch):
    """The typo check on this route is only as good as the listing behind it.
    Asked without the key, a hosted endpoint answers nothing, `served` is empty
    and the check is skipped -- so a model that does not exist got written into
    the file, which is the one thing this route exists to prevent."""
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-real")
    _keyed(monkeypatch, "POIEO_TEST_KEY", Catalogue((Served(id="qwen3.5:latest"),)))
    binding = _BLOCK.replace("base_url: http://localhost:11434", "base_url: http://x\n    api_key_env: POIEO_TEST_KEY")
    client = _client(tmp_path, binding=binding, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = _use(client, "local/a-model-nobody-serves")

    assert reply.status_code == 409
    assert "does not serve" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before


def test_using_a_model_for_one_role_leaves_the_default_alone(tmp_path, monkeypatch):
    _asks(monkeypatch, {"ollama": Catalogue((Served(id="llama3.2:3b"),))})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _use(client, "local/llama3.2:3b", role="reader")

    assert reply.status_code == 200
    assert reply.json()["role"] == "reader"
    text = (tmp_path / "b.yaml").read_text(encoding="utf-8")
    # The role moved; the default did not.
    assert text.index("llama3.2:3b") > text.index("default:")
    assert 'model: "qwen3.5:latest"' in text


def test_a_reference_without_a_slash_is_refused_in_the_products_voice(tmp_path, monkeypatch):
    """400 and not 409: the argument is malformed, not the state."""
    _asks(monkeypatch)
    before = (tmp_path / "b.yaml").read_bytes() if (tmp_path / "b.yaml").exists() else None
    client = _client(tmp_path)
    before = (tmp_path / "b.yaml").read_bytes()

    reply = _use(client, "just-a-name")

    assert reply.status_code == 400
    assert "provider/model" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_bytes() == before


def test_a_provider_that_is_not_declared_is_refused_and_names_the_ones_that_are(tmp_path, monkeypatch):
    _asks(monkeypatch)
    client = _client(tmp_path, binding=_TWO)
    before = (tmp_path / "b.yaml").read_bytes()

    reply = _use(client, "nowhere/m")

    assert reply.status_code == 409
    assert sorted(reply.json()["providers"]) == ["local", "routed"]
    assert (tmp_path / "b.yaml").read_bytes() == before


def test_a_model_the_endpoint_says_it_does_not_serve_is_refused_with_what_it_has(tmp_path, monkeypatch):
    """The typo this pair exists to prevent: a model named from memory does not
    fail here, it fails at 3am in a run."""
    _asks(monkeypatch)
    client = _client(tmp_path, binding=_TWO)
    before = (tmp_path / "b.yaml").read_bytes()

    reply = _use(client, "local/qwen9.9:imagined")

    assert reply.status_code == 409
    assert reply.json()["models"] == ["qwen3.5:latest"]
    assert (tmp_path / "b.yaml").read_bytes() == before


def test_an_endpoint_that_did_not_answer_does_not_block_the_edit_and_says_so(tmp_path, monkeypatch):
    """A laptop with its server switched off still gets to edit its own config,
    exactly as `poieo config use` allows -- silence is not agreement, so the
    reply says the name could not be checked rather than implying it was."""

    async def silent(type_, base_url=None, limit=None, api_key_env=None):
        return Catalogue()

    monkeypatch.setattr(detect_module, "catalogue_for", silent)
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _use(client, "local/anything-at-all")

    assert reply.status_code == 200
    assert reply.json()["checked"] is False


def test_a_shape_the_file_does_not_allow_is_refused_and_the_file_is_untouched(tmp_path, monkeypatch):
    """Flow-style YAML is legal, rare, and exactly where guessing corrupts a
    config. `rebind` refuses before writing and names the key; the route says
    so in its own words rather than swallowing it."""
    _asks(monkeypatch)
    flow = (
        "name: flow\nproviders:\n"
        '  local: {type: ollama, base_url: "http://localhost:11434"}\n'
        'default: {provider: local, model: "qwen3.5:latest"}\n'
    )
    client = _client(tmp_path, binding=flow, tasks=False)
    before = (tmp_path / "b.yaml").read_bytes()

    reply = _use(client, "local/qwen3.5:latest")

    assert reply.status_code == 409
    assert "by hand" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_bytes() == before


def test_using_a_model_on_an_unknown_project_is_404(tmp_path, monkeypatch):
    _asks(monkeypatch)
    reply = _use(_client(tmp_path), "fake/m2", project="gone")

    assert reply.status_code == 404
    assert reply.json()["projects"] == ["board"]


def test_a_get_on_the_write_route_is_not_allowed(tmp_path, monkeypatch):
    _asks(monkeypatch)
    client = _client(tmp_path)
    before = (tmp_path / "b.yaml").read_bytes()

    assert client.get("/api/projects/board/models/use").status_code == 405
    assert (tmp_path / "b.yaml").read_bytes() == before


def test_a_refusal_never_carries_the_key_it_is_about(tmp_path, monkeypatch):
    """A refusal message is where a value is likeliest to be interpolated by
    accident."""
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-planted-by-this-test")
    _asks(monkeypatch)
    binding = _MOCK.replace("fake: {type: mock,", "fake: {type: mock, api_key_env: POIEO_TEST_KEY,")
    client = _client(tmp_path, binding=binding)

    reply = _use(client, "nowhere/m")

    assert reply.status_code == 409
    assert "sk-planted-by-this-test" not in reply.text


async def test_the_board_and_the_daemon_agree_about_the_model_after_a_use(tmp_path, monkeypatch):
    """The one this whole slice exists to make pass.

    `/api/tasks` draws each node's model off the spec in memory. Without the
    reread behind the write, the file and the picture part company the moment
    somebody clicks, and the reader is looking at two answers to one question.

    Served for real and driven on one event loop, as uvicorn shares the
    daemon's: the nodes a board paints come off runners, and runners exist only
    once `serve()` has built them.
    """
    _asks(monkeypatch, {"ollama": Catalogue((Served(id="llama3.2:3b"),))})
    (tmp_path / "b.yaml").write_text(_BLOCK, encoding="utf-8")
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    card(tmp_path / "cards", "f", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    (tmp_path / "poieo.yaml").write_text("name: board\ntasks: cards\nbinding: b.yaml\n", encoding="utf-8")
    daemon = Daemon(load_config(tmp_path / "poieo.yaml"), store=NullStore())
    serving = asyncio.create_task(daemon.serve(install_signals=False))
    while not daemon.runners:
        await asyncio.sleep(0.01)

    transport = httpx.ASGITransport(app=create_app(daemon))
    async with httpx.AsyncClient(transport=transport, base_url="http://poieo") as client:

        async def painted():
            body = (await client.get("/api/tasks")).json()
            return body["tasks"][0]["shape"]["nodes"][0]["model"]

        assert await painted() == "qwen3.5:latest"

        reply = await client.post(
            "/api/projects/board/models/use",
            json={"target": "local/llama3.2:3b", "role": "reader"},
        )
        assert reply.status_code == 200

        assert await painted() == "llama3.2:3b"

    daemon.stop()
    await asyncio.wait_for(serving, timeout=10)


def test_the_panel_offers_the_roles_the_file_names(tmp_path, monkeypatch):
    """`default` plus what the binding declares, and nothing else. Offering a
    role a graph calls but the file never named would let the panel create the
    `role: classifer` typo docs/binding.md spends a page warning about."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_BLOCK, tasks=False)).json()

    assert body["roles"] == ["default", "reader"]


# -- engines running here that this project has never used -------------------
#
# Detection runs once, at `init`. Install Ollama the week after and the binding
# has never heard of it, so the panel shows nothing from it -- and shows no
# reason why either, which reads as "there is nothing there". So the addresses
# `CANDIDATES` knows are asked too, and whatever answers that this project
# cannot reach is offered.
#
# On **its own route**, measured rather than assumed: a candidate port nothing
# is listening on costs a full `HTTP_TIMEOUT` rather than refusing fast, so
# folding this into the catalogue would have added a second and a half to every
# paint of it. Asked apart, nothing waits on it.
#
# It is an offer, never an edit: writing the file is `models/add` below, which
# a person presses.


def _machine(monkeypatch, at):
    """What answers at each address, so a test can put an engine on a port.

    Keyed by address rather than by type, because the address is what the
    offer turns on: a declared endpoint and a candidate are routinely the same
    type, and telling them apart by type would make every test here pass for
    the wrong reason.
    """

    async def fake(type_, base_url=None, limit=None, api_key_env=None):
        return at.get(base_url, Catalogue())

    monkeypatch.setattr(detect_module, "catalogue_for", fake)


_OLLAMA = "http://localhost:11434"
_LMSTUDIO = "http://localhost:1234/v1"
_VLLM = "http://localhost:8000/v1"

# A binding that reaches nothing on this machine, so every candidate that
# answers is one this project cannot use.
_NOWHERE = """name: nowhere
providers:
  routed:
    type: openai_compatible
    base_url: https://openrouter.ai/api/v1
default:
  provider: routed
  model: qwen/flash
"""


def _look(client, project="board"):
    return client.get(f"/api/projects/{project}/models/undeclared")


def _offered(body):
    return {one["name"]: one for one in body["undeclared"]}


def test_the_catalogue_does_not_go_looking_for_engines(tmp_path, monkeypatch):
    """The measurement this split exists for. A candidate nothing is listening
    on does not refuse -- it costs the whole `HTTP_TIMEOUT` -- so a catalogue
    that searched for new engines while it was at it would have taken a second
    and a half to draw a list it already had every answer for."""
    asked = []

    async def fake(type_, base_url=None, limit=None, api_key_env=None):
        asked.append(base_url)
        return Catalogue()

    monkeypatch.setattr(detect_module, "catalogue_for", fake)
    _models(_client(tmp_path, binding=_NOWHERE, tasks=False))

    assert asked == ["https://openrouter.ai/api/v1"]


def test_an_engine_answering_here_that_this_project_cannot_reach_is_offered(tmp_path, monkeypatch):
    _machine(monkeypatch, {_LMSTUDIO: Catalogue((Served(id="qwen3-4b"),))})
    body = _look(_client(tmp_path, binding=_NOWHERE, tasks=False)).json()

    offer = _offered(body)["lmstudio"]
    assert offer["label"] == "LM Studio"
    assert offer["models"] == ["qwen3-4b"]


def test_an_engine_this_project_already_declares_is_not_offered(tmp_path, monkeypatch):
    _machine(monkeypatch, {_OLLAMA: Catalogue((Served(id="qwen3.5:latest"),))})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    assert _look(client).json()["undeclared"] == []
    assert [e["name"] for e in _models(client).json()["endpoints"]] == ["local"]


def test_an_engine_declared_under_another_name_is_not_offered_again(tmp_path, monkeypatch):
    """The offer is about an address, not a key. Somebody who declared the
    vLLM on this machine as `fast` has it already; asking them to add it a
    second time under the name detection would have picked writes the same
    server into the file twice."""
    binding = """name: renamed
providers:
  fast:
    type: openai_compatible
    base_url: http://localhost:8000/v1
default:
  provider: fast
  model: qwen3-32b
"""
    _machine(monkeypatch, {_VLLM: Catalogue((Served(id="qwen3-32b"),))})
    body = _look(_client(tmp_path, binding=binding, tasks=False)).json()

    assert body["undeclared"] == []


def test_the_same_address_spelled_two_ways_is_still_one_endpoint(tmp_path, monkeypatch):
    """`127.0.0.1` and `localhost` are the same machine and a config may say
    either; a trailing slash is nobody's second endpoint."""
    binding = _BLOCK.replace("http://localhost:11434", "http://127.0.0.1:11434/")
    _machine(monkeypatch, {_OLLAMA: Catalogue((Served(id="qwen3.5:latest"),))})
    body = _look(_client(tmp_path, binding=binding, tasks=False)).json()

    assert body["undeclared"] == []


def test_an_engine_that_answers_with_nothing_is_not_offered(tmp_path, monkeypatch):
    """The rule `probe` already holds: naming an engine that serves nothing
    writes a binding that fails on the project's first run."""
    _machine(monkeypatch, {_LMSTUDIO: Catalogue()})
    body = _look(_client(tmp_path, binding=_NOWHERE, tasks=False)).json()

    assert body["undeclared"] == []


def test_the_offer_carries_no_address(tmp_path, monkeypatch):
    """Same fence as the endpoints beside it. The board never needs to know
    where an engine lives -- it names one back by key, and the daemon looks the
    address up in the table it detects from."""
    _machine(monkeypatch, {_LMSTUDIO: Catalogue((Served(id="qwen3-4b"),))})
    response = _look(_client(tmp_path, binding=_NOWHERE, tasks=False))

    assert _offered(response.json())["lmstudio"]["models"] == ["qwen3-4b"]
    assert "localhost" not in response.text
    assert "1234" not in response.text


def test_a_project_that_names_no_binding_is_not_asked_about_engines(tmp_path, monkeypatch):
    """There is nowhere to write an answer to, so the four addresses are not
    worth a round trip."""
    asked: list[str | None] = []

    async def fake(type_, base_url=None, limit=None, api_key_env=None):
        asked.append(base_url)
        return Catalogue()

    monkeypatch.setattr(detect_module, "catalogue_for", fake)
    (tmp_path / "cards").mkdir()
    path = tmp_path / "poieo.yaml"
    path.write_text("name: board\ntasks: cards\n", encoding="utf-8")
    client = TestClient(create_app(Daemon(load_config(path), store=NullStore())))

    assert _look(client).json()["undeclared"] == []
    assert asked == []


# -- letting this project use an engine that is already running --------------
#
# The second write on this route, and the same fence: it may write the
# project's binding file and nothing else, and never accepts or returns a
# credential. It goes through `rebind.declare`, so it is the same edit
# `poieo config add` makes -- and, like that command, it only ever *adds*.
# Nothing about what a role uses moves; choosing is what `models/use` is for.


def _add(client, engine, project="board"):
    return client.post(f"/api/projects/{project}/models/add", json={"engine": engine})


def test_adding_an_engine_writes_it_into_the_binding(tmp_path, monkeypatch):
    _machine(monkeypatch, {_LMSTUDIO: Catalogue((Served(id="qwen3-4b"),))})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _add(client, "lmstudio")

    assert reply.status_code == 200
    assert reply.json() == {"status": "added", "engine": "lmstudio", "models": ["qwen3-4b"]}
    written = (tmp_path / "b.yaml").read_text(encoding="utf-8")
    assert "lmstudio:" in written
    assert "type: openai_compatible" in written
    assert "base_url: http://localhost:1234/v1" in written


def test_adding_an_engine_moves_nothing_that_is_already_in_use(tmp_path, monkeypatch):
    """Declaring a model and choosing one are different decisions, and this is
    the first. A panel that quietly repointed the default would change what
    every unattended run does."""
    _machine(monkeypatch, {_LMSTUDIO: Catalogue((Served(id="qwen3-4b"),))})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    assert _add(client, "lmstudio").status_code == 200

    body = _models(client).json()
    assert body["endpoints"][0]["name"] == "local"
    written = (tmp_path / "b.yaml").read_text(encoding="utf-8")
    assert 'default:\n  provider: local\n  model: "qwen3.5:latest"' in written


def test_an_engine_already_in_the_file_is_refused_and_the_file_is_untouched(tmp_path, monkeypatch):
    """The offer is drawn from a report taken a moment ago; between the paint
    and the press somebody may have added it in a terminal."""
    _machine(monkeypatch, {_OLLAMA: Catalogue((Served(id="qwen3.5:latest"),))})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = _add(client, "ollama")

    assert reply.status_code == 409
    assert "already" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before


def test_an_engine_nobody_detects_is_refused_by_name(tmp_path, monkeypatch):
    """400 and not 409: the argument names nothing this knows how to look for,
    which is malformed rather than a state that could change."""
    _machine(monkeypatch, {})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _add(client, "not-an-engine")

    assert reply.status_code == 400
    assert "lmstudio" in reply.json()["engines"]


def test_an_engine_that_has_stopped_answering_is_not_written(tmp_path, monkeypatch):
    """It answered when the panel was painted and does not now. Writing it
    would put an address in the file that fails on the project's next run --
    the rule `probe` holds, held here too because the press is a second trip."""
    _machine(monkeypatch, {})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = _add(client, "lmstudio")

    assert reply.status_code == 409
    assert "not answering" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before


def test_a_file_that_cannot_be_added_to_is_refused_in_rebinds_own_words(tmp_path, monkeypatch):
    """A whole `providers:` written on one line, which is legal YAML and not a
    shape anything can be appended to. `rebind` writes, sees the result will
    not load, and puts the file back exactly as it was -- so the refusal is
    what the reader gets, not a corrupted config.

    Note `_TWO` is *not* this case, though it looks close: block-form
    `providers:` with flow-style children takes an addition fine, because
    adding only ever appends a sibling and never edits inside one.
    """
    flow = 'name: flow\nproviders: {local: {type: ollama, base_url: "http://localhost:11434"}}\n'
    flow += 'default: {provider: local, model: "qwen3.5:latest"}\n'
    _machine(monkeypatch, {_LMSTUDIO: Catalogue((Served(id="qwen3-4b"),))})
    client = _client(tmp_path, binding=flow, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = _add(client, "lmstudio")

    assert reply.status_code == 409
    assert "b.yaml" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before


def test_adding_an_engine_to_an_unknown_project_is_404(tmp_path, monkeypatch):
    _machine(monkeypatch, {})
    reply = _add(_client(tmp_path, tasks=False), "lmstudio", project="ghost")

    assert reply.status_code == 404
    assert reply.json()["projects"] == ["board"]


def test_a_get_on_the_add_route_is_not_allowed(tmp_path, monkeypatch):
    _machine(monkeypatch, {})
    client = _client(tmp_path, tasks=False)

    assert client.get("/api/projects/board/models/add").status_code == 405


def test_adding_an_engine_never_carries_a_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-planted-by-this-test")
    _machine(monkeypatch, {_LMSTUDIO: Catalogue((Served(id="qwen3-4b"),))})
    binding = _BLOCK.replace("    type: ollama\n", "    type: ollama\n    api_key_env: POIEO_TEST_KEY\n")
    client = _client(tmp_path, binding=binding, tasks=False)

    reply = _add(client, "lmstudio")

    assert reply.status_code == 200
    assert "sk-planted-by-this-test" not in reply.text


def test_the_new_endpoint_is_listed_without_a_restart(tmp_path, monkeypatch):
    """The whole point of pressing it. The daemon re-reads the file it just
    wrote, so the endpoint the next paint asks is the one now on disk.

    Over a project **with a task on this binding**, which is the case the
    reread exists for: the panel then answers from the spec in memory, and
    without the reread it would go on describing the file as it was at start-up
    however many times the reader pressed.
    """
    _machine(
        monkeypatch,
        {
            _OLLAMA: Catalogue((Served(id="qwen3.5:latest"),)),
            _LMSTUDIO: Catalogue((Served(id="qwen3-4b"),)),
        },
    )
    client = _client(tmp_path, binding=_BLOCK, tasks=True)
    assert [e["name"] for e in _models(client).json()["endpoints"]] == ["local"]

    _add(client, "lmstudio")

    body = _models(client).json()
    assert [e["name"] for e in body["endpoints"]] == ["local", "lmstudio"]
    assert [m["id"] for m in _endpoints(body)["lmstudio"]["models"]] == ["qwen3-4b"]
    # And it is no longer something to offer, because it is now declared.
    assert _look(client).json()["undeclared"] == []


def test_an_offer_says_which_product_answered_not_the_pair_that_share_a_port(tmp_path, monkeypatch):
    """vLLM and SGLang default to the same port, so the address can never tell
    them apart and the candidate's own label is the pair. What can tell them
    apart is the server, which names itself on its listing -- and reading it
    back off the binding would be believing what its author typed."""
    monkeypatch.setattr(
        detect_module,
        "catalogue_for",
        lambda type_, base_url=None, limit=None, api_key_env=None: _answers(
            Catalogue((Served(id="qwen3-32b"),), "SGLang") if base_url == _VLLM else Catalogue()
        ),
    )
    body = _look(_client(tmp_path, binding=_NOWHERE, tasks=False)).json()

    assert _offered(body)["vllm"]["label"] == "SGLang"


def _answers(catalogue):
    async def ready():
        return catalogue

    return ready()


# -- this machine, or somebody else's ----------------------------------------
#
# An inference server is routinely somewhere else: an Ollama on the desktop
# under the desk, a vLLM on an office box. The listing it answers with means
# the same thing either way -- models pulled and ready, not a menu -- but *whose
# machine* they are pulled onto is a second fact, and it comes from the address.
#
# It used to come from the provider type, so every Ollama anywhere read as "on
# this machine". Found by declaring one at a network address and reading the
# panel back.

_ELSEWHERE = """\
name: two-ollamas
providers:
  here: {type: ollama, base_url: "http://localhost:11434"}
  office: {type: ollama, base_url: "http://192.168.1.50:11434"}
default: {provider: here, model: "qwen3.5:latest"}
"""


def test_an_ollama_on_another_host_is_not_called_this_machine(tmp_path, monkeypatch):
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_ELSEWHERE)).json()

    at = _endpoints(body)
    assert at["here"]["here"] is True
    assert at["office"]["here"] is False
    # Both still list what is *pulled* rather than a catalogue: that is the
    # backend's property and does not move with the address.
    assert at["here"]["installed"] is True
    assert at["office"]["installed"] is True


def test_two_endpoints_of_one_kind_are_told_apart_by_their_host(tmp_path, monkeypatch):
    """Both are `Ollama`, and `poieo config` would name both `ollama`. The
    address is the only thing that separates them."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path, binding=_ELSEWHERE)).json()

    at = _endpoints(body)
    assert at["here"]["host"] == "localhost:11434"
    assert at["office"]["host"] == "192.168.1.50:11434"


def test_every_way_of_writing_this_machine_is_this_machine(tmp_path, monkeypatch):
    """A config may say any of these and mean the same box."""
    binding = _ELSEWHERE.replace('"http://192.168.1.50:11434"', '"http://127.0.0.1:11500"')
    _asks(monkeypatch)
    assert _endpoints(_models(_client(tmp_path, binding=binding)).json())["office"]["here"] is True

    binding = _ELSEWHERE.replace('"http://192.168.1.50:11434"', '"http://[::1]:11500/v1"')
    assert _endpoints(_models(_client(tmp_path, binding=binding)).json())["office"]["here"] is True


def test_an_endpoint_with_no_address_is_neither_here_nor_elsewhere(tmp_path, monkeypatch):
    """Claude's SDK resolves its own address and `mock` has none at all. Null,
    not false: "somewhere else" would be a claim about a machine nobody named."""
    _asks(monkeypatch)
    body = _models(_client(tmp_path)).json()

    assert _endpoints(body)["fake"]["here"] is None
    assert _endpoints(body)["fake"]["host"] is None


# -- an edit the running daemon will not take --------------------------------
#
# `point_at` writes the file and verifies it reloads; `daemon.reread` then
# validates it the way start-up would and may refuse -- a role pointed at an
# endpoint whose key is not set is the case that happens. The route used to
# swallow that, on the reasoning that the next run would report it.
#
# Found by clicking it on a real board. The file changed, the answer said
# `using`, and the panel went on showing the old model, because the panel reads
# the spec in memory and the daemon had kept the old one. Three answers to one
# question, and the only visible one was wrong.

_KEYLESS = """name: keyless
providers:
  local:
    type: ollama
    base_url: http://localhost:11434
  routed:
    type: openai_compatible
    base_url: https://openrouter.ai/api/v1
    api_key_env: POIEO_ABSENT_KEY
default:
  provider: local
  model: "qwen3.5:latest"
roles:
  reader:
    provider: local
    model: "qwen3.5:latest"
"""


def test_a_change_the_daemon_will_not_take_says_so_and_says_why(tmp_path, monkeypatch):
    monkeypatch.delenv("POIEO_ABSENT_KEY", raising=False)
    _asks(monkeypatch, {"openai_compatible": Catalogue((Served(id="qwen/flash"),))})
    client = _client(tmp_path, binding=_KEYLESS, tasks=True)

    reply = _use(client, "routed/qwen/flash", role="reader")
    body = reply.json()

    assert reply.status_code == 200
    assert body["status"] == "using"
    # The file really did change -- this is not a refusal.
    assert "provider: routed" in (tmp_path / "b.yaml").read_text(encoding="utf-8")
    # But the running daemon kept the last good spec, so the panel is about to
    # redraw the *old* model, and silence would read as "nothing happened".
    assert body["adopted"] is False
    assert "POIEO_ABSENT_KEY" in body["why"]


def test_a_change_the_daemon_takes_says_that_too(tmp_path, monkeypatch):
    """The ordinary case, said out loud rather than implied by the absence of
    a warning."""
    _asks(monkeypatch, {"ollama": Catalogue((Served(id="llama3.2:3b"),))})
    client = _client(tmp_path, binding=_KEYLESS, tasks=True)

    body = _use(client, "local/llama3.2:3b", role="reader").json()

    assert body["adopted"] is True
    assert "why" not in body


def test_a_warning_about_a_key_never_carries_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("POIEO_ABSENT_KEY", "")
    _asks(monkeypatch, {"openai_compatible": Catalogue((Served(id="qwen/flash"),))})
    client = _client(tmp_path, binding=_KEYLESS, tasks=True)
    monkeypatch.setenv("POIEO_ABSENT_KEY", "sk-planted-by-this-test")

    reply = _use(client, "routed/qwen/flash", role="reader")

    assert "sk-planted-by-this-test" not in reply.text


# -- an engine at an address the board was not told about --------------------
#
# The offer above covers the four ports on this machine. Everything else -- a
# vLLM on 8001, an Ollama on a desktop, an office box -- had no route at all,
# and DESIGN.md's "everything is reachable from a terminal" cuts both ways: the
# terminal grew `poieo config add <url>` in the same change, and this is that
# command, through the same `detect.ask` and the same `rebind.declare`.


def _found(monkeypatch, engine, wants: str | None = None):
    """`detect.ask`, stood in for.

    ``wants`` names the variable this endpoint refuses to list without -- what
    every hosted endpoint does. It has to be both named *and* set, since that is
    when the real `ask` has a key to send; without one the address answers as
    though nothing were there, which is what a 401 means to detection. ``None``
    is an endpoint that lists for anyone.
    """

    async def fake(base_url, key_env=None):
        if not engine or base_url != engine.base_url:
            return None
        if wants is not None and not (key_env == wants and os.environ.get(wants)):
            return None
        return replace(engine, api_key_env=key_env or None)

    monkeypatch.setattr(detect_module, "ask", fake)


def _add_at(client, url, project="board", **rest):
    return client.post(f"/api/projects/{project}/models/add", json={"url": url, **rest})


_OFFICE = detect_module.Engine("gpu-box", "gpu-box", "openai_compatible", ("qwen3-32b",), "http://gpu-box:8001/v1")


def test_an_address_is_asked_and_what_it_is_comes_back(tmp_path, monkeypatch):
    """The reader types an address and nothing else: which backend it is comes
    from asking, not from a form asking them to classify their own server."""
    _machine(monkeypatch, {})
    _found(monkeypatch, _OFFICE)
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _add_at(client, "http://gpu-box:8001/v1")

    assert reply.status_code == 200
    assert reply.json() == {
        "status": "added",
        "engine": "gpu-box",
        "models": ["qwen3-32b"],
    }
    written = (tmp_path / "b.yaml").read_text(encoding="utf-8")
    assert "  gpu-box:\n    type: openai_compatible\n" in written
    assert "base_url: http://gpu-box:8001/v1" in written


def test_an_address_with_nothing_on_it_is_refused_and_writes_nothing(tmp_path, monkeypatch):
    _machine(monkeypatch, {})
    _found(monkeypatch, None)
    client = _client(tmp_path, binding=_BLOCK, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = _add_at(client, "http://nowhere:9999")

    assert reply.status_code == 409
    assert "nowhere:9999" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before


def test_an_address_may_be_given_the_name_the_reader_wants(tmp_path, monkeypatch):
    """Two vLLMs is the ordinary case and both would be called `vllm`."""
    _machine(monkeypatch, {})
    _found(monkeypatch, _OFFICE)
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _add_at(client, "http://gpu-box:8001/v1", name="office")

    assert reply.json()["engine"] == "office"
    assert "  office:\n" in (tmp_path / "b.yaml").read_text(encoding="utf-8")


def test_an_address_takes_the_name_of_a_variable_and_never_a_key(tmp_path, monkeypatch):
    """The fence, at the one place a hosted endpoint makes it tempting. A
    variable's name is not a secret and belongs in the file; the value is one
    and never crosses.

    The endpoint here lists nothing until the request carries the key, which is
    what every hosted one does -- so this also says the key is asked *with* and
    not merely written down afterwards.
    """
    _machine(monkeypatch, {})
    monkeypatch.setenv("OFFICE_TOKEN", "sk-real")
    _found(monkeypatch, _OFFICE, wants="OFFICE_TOKEN")
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _add_at(client, "http://gpu-box:8001/v1", key_env="OFFICE_TOKEN", api_key="sk-nope")

    assert reply.status_code == 200
    written = (tmp_path / "b.yaml").read_text(encoding="utf-8")
    assert "api_key_env: OFFICE_TOKEN" in written
    assert "sk-nope" not in written
    assert "sk-nope" not in reply.text


def test_a_variable_the_daemon_cannot_read_is_said_out_loud(tmp_path, monkeypatch):
    """Left to detection this came back as "nothing usable answered at ..." --
    true, and about the wrong problem. The daemon's environment is not the
    reader's shell, so which one it is missing from matters."""
    _machine(monkeypatch, {})
    monkeypatch.delenv("OFFICE_TOKEN", raising=False)
    _found(monkeypatch, _OFFICE, wants="OFFICE_TOKEN")
    client = _client(tmp_path, binding=_BLOCK, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = _add_at(client, "http://gpu-box:8001/v1", key_env="OFFICE_TOKEN")

    assert reply.status_code == 409
    assert "OFFICE_TOKEN" in reply.json()["error"] and "not set" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before


def test_an_endpoint_that_lists_without_a_key_still_takes_the_name(tmp_path, monkeypatch):
    """An unset variable is not a precondition, and must not be one. The key
    routinely lives in the environment a wrapper starts the daemon under, and
    writing its name into a file people commit is a whole reason to do this."""
    _machine(monkeypatch, {})
    monkeypatch.delenv("OFFICE_TOKEN", raising=False)
    _found(monkeypatch, _OFFICE)  # lists for anyone
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    reply = _add_at(client, "http://gpu-box:8001/v1", key_env="OFFICE_TOKEN")

    assert reply.status_code == 200, reply.text
    assert "api_key_env: OFFICE_TOKEN" in (tmp_path / "b.yaml").read_text(encoding="utf-8")


def test_a_key_variable_with_no_address_is_refused_rather_than_dropped(tmp_path, monkeypatch):
    """The four ports on this machine are not endpoints a key opens, and there
    is no saying which of them it was meant for. Read only inside the address
    branch, it went nowhere and answered 200 -- leaving a caller believing they
    had declared a keyed endpoint they had not."""
    _machine(monkeypatch, {_OLLAMA: Catalogue((Served(id="qwen3:32b"),))})
    monkeypatch.setenv("OFFICE_TOKEN", "sk-real")
    client = _client(tmp_path, binding=_BLOCK, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = client.post("/api/projects/board/models/add", json={"engine": "ollama", "key_env": "OFFICE_TOKEN"})

    assert reply.status_code == 400
    assert "address" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before


def test_a_name_already_in_the_file_is_refused_rather_than_overwritten(tmp_path, monkeypatch):
    _machine(monkeypatch, {})
    _found(monkeypatch, _OFFICE)
    client = _client(tmp_path, binding=_BLOCK, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = _add_at(client, "http://gpu-box:8001/v1", name="local")

    assert reply.status_code == 409
    assert "local" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before


def test_a_body_with_neither_an_engine_nor_an_address_is_refused(tmp_path, monkeypatch):
    _machine(monkeypatch, {})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)

    assert client.post("/api/projects/board/models/add", json={}).status_code == 400


def test_an_address_the_project_can_reach_is_listed_without_a_restart(tmp_path, monkeypatch):
    _machine(monkeypatch, {_OLLAMA: Catalogue((Served(id="qwen3.5:latest"),))})
    _found(monkeypatch, _OFFICE)
    client = _client(tmp_path, binding=_BLOCK, tasks=True)

    assert _add_at(client, "http://gpu-box:8001/v1").status_code == 200

    assert [e["name"] for e in _models(client).json()["endpoints"]] == ["local", "gpu-box"]


# -- one address, spelled however the file spells it --------------------------
#
# The offer decides "this project cannot reach that" by comparing addresses,
# and did it with its own string rules while `detect` grew a second set for
# `here`. The weaker one was wrong three ways, and the worst of them was
# self-inflicted: `detect.ask` writes `http://localhost:8000` for a server that
# answers at its root, and the panel then offered to add that same server again.


def _offers_vllm(tmp_path, monkeypatch, declared_at):
    binding = f"""name: n
providers:
  mine: {{type: openai_compatible, base_url: "{declared_at}"}}
default: {{provider: mine, model: m}}
"""
    _machine(monkeypatch, {_VLLM: Catalogue((Served(id="qwen3-32b"),))})
    body = _look(_client(tmp_path, binding=binding, tasks=False)).json()
    return "vllm" in _offered(body)


def test_a_server_already_declared_is_not_offered_however_its_address_is_written(tmp_path, monkeypatch):
    """One port is one server. Which path it hangs its listing on, and which of
    the four spellings of this machine the file used, are not second servers."""
    for spelling in (
        "http://localhost:8000/v1",
        # What `detect.ask` itself writes for a server answering at its root.
        "http://localhost:8000",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
        "http://127.0.0.2:8000",
        "http://LOCALHOST:8000/v1",
    ):
        assert not _offers_vllm(tmp_path, monkeypatch, spelling), spelling


def test_the_same_port_on_another_machine_is_another_server(tmp_path, monkeypatch):
    """The comparison must not go so far that a real second endpoint vanishes."""
    assert _offers_vllm(tmp_path, monkeypatch, "http://192.168.1.50:8000/v1")


def test_another_port_on_this_machine_is_another_server(tmp_path, monkeypatch):
    assert _offers_vllm(tmp_path, monkeypatch, "http://localhost:8001/v1")


def test_an_address_with_a_typo_in_it_is_a_refusal_and_not_a_crash(tmp_path, monkeypatch):
    """This route is on a bare Starlette with no exception handlers, so an
    address detection raised on was a 500 over a request that never touched a
    file. A port that is not a number is the ordinary way to get one."""
    _machine(monkeypatch, {})
    client = _client(tmp_path, binding=_BLOCK, tasks=False)
    before = (tmp_path / "b.yaml").read_text(encoding="utf-8")

    reply = _add_at(client, "http://gpu-box:80O1")

    assert reply.status_code == 400
    assert "80O1" in reply.json()["error"]
    assert (tmp_path / "b.yaml").read_text(encoding="utf-8") == before
