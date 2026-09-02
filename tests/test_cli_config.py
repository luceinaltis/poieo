"""`poieo config` answers "what is this project bound to, and what else could
it name?" -- the second half live, from the endpoints themselves, because a
model list written down a month ago is a list that has since gone wrong.
"""

import json

import pytest
from typer.testing import CliRunner

from poieo import detect as detect_module
from poieo.cli import app

runner = CliRunner()


BINDING = """\
name: default
version: 1

providers:
  ollama:
    type: ollama
    base_url: http://localhost:11434
  claude:
    type: anthropic

default:
  provider: ollama
  model: "qwen3:32b"
  params:
    max_tokens: 2048

roles:
  classifier:
    provider: ollama
    model: "llama3.2:3b"
"""


def _project(tmp_path, binding: str = BINDING):
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models" / "default.yaml").write_text(binding, encoding="utf-8")
    (tmp_path / "tasks").mkdir(exist_ok=True)
    (tmp_path / "poieo.yaml").write_text(
        "version: 1\nstore: runs\nbinding: models/default.yaml\ntasks: tasks/\n",
        encoding="utf-8",
    )
    return tmp_path


def _serving(monkeypatch, answers: "dict[tuple[str, str | None], tuple[str, ...]]"):
    """What each (type, base_url) endpoint serves right now, for this test.

    Anything not named is unreachable -- which is a real answer, not a crash:
    `poieo config models` has to work with the laptop's Ollama switched off.
    """

    async def models_for(type_, base_url=None, api_key_env=None):
        return answers.get((type_, base_url), ())

    monkeypatch.setattr(detect_module, "models_for", models_for)


# -- poieo config -------------------------------------------------------------


def test_config_outside_a_project_refuses_in_the_usual_words(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 1
    assert "poieo.yaml" in result.stderr and "poieo init" in result.stderr


def test_config_says_what_the_project_is_bound_to(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0, result.output
    # Where the answer came from, so nothing here is magic. Spelled absolutely,
    # as `validate` and `run` spell it, so the separator is the platform's.
    assert str(tmp_path / "models" / "default.yaml") in result.stdout
    # The two declared endpoints, with the address a role would reach.
    assert "ollama" in result.stdout and "http://localhost:11434" in result.stdout
    assert "anthropic" in result.stdout
    # What an unnamed role gets, and the one role that was named.
    assert "qwen3:32b" in result.stdout
    assert "classifier" in result.stdout and "llama3.2:3b" in result.stdout


def test_config_does_not_reach_the_network(tmp_path, monkeypatch):
    """Reading a file is not probing a server. `poieo check` is the one that
    talks to an endpoint, and `config models` the one that asks what it has."""
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    async def explode(*args, **kwargs):
        raise AssertionError("poieo config probed an endpoint")

    monkeypatch.setattr(detect_module, "models_for", explode)
    assert runner.invoke(app, ["config"]).exit_code == 0


def test_config_json_is_parseable_for_an_agent(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["config", "--json"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["binding"]["name"] == "default"
    # Slash-separated: the form `poieo config use` takes back, so what a
    # reader copies out of here is a thing they can type in.
    assert report["default"] == "ollama/qwen3:32b"
    assert report["roles"] == {"classifier": "ollama/llama3.2:3b"}
    assert report["providers"]["ollama"]["base_url"] == "http://localhost:11434"


# -- poieo config models ------------------------------------------------------


def test_config_models_lists_what_each_provider_serves_now(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(
        monkeypatch,
        {
            ("ollama", "http://localhost:11434"): ("qwen3:32b", "llama3.2:3b"),
            ("anthropic", None): ("claude-opus-5",),
        },
    )

    result = runner.invoke(app, ["config", "models"])

    assert result.exit_code == 0, result.output
    for model in ("qwen3:32b", "llama3.2:3b", "claude-opus-5"):
        assert model in result.stdout, model


def test_config_models_asks_a_keyed_endpoint_with_the_variable_it_names(tmp_path, monkeypatch):
    """A hosted endpoint answers 401 to an unauthenticated listing, and 401 is
    silence to detection -- so this printed "no answer" beside an endpoint that
    was working perfectly, and the reader had nothing to choose from."""
    _project(tmp_path, BINDING.replace("    type: anthropic", "    type: anthropic\n    api_key_env: OFFICE_TOKEN"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OFFICE_TOKEN", "sk-real")

    async def models_for(type_, base_url=None, api_key_env=None):
        return ("claude-opus-5",) if (type_, api_key_env) == ("anthropic", "OFFICE_TOKEN") else ()

    monkeypatch.setattr(detect_module, "models_for", models_for)

    result = runner.invoke(app, ["config", "models"])

    assert result.exit_code == 0, result.output
    assert "claude-opus-5" in result.stdout


def test_config_models_marks_what_is_already_in_use(tmp_path, monkeypatch):
    """The list exists to be chosen from, so it has to say what is spoken for
    -- otherwise the next question is always "which one am I on?"."""
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    # The third is longer than the column the marker lines up on: a real
    # Ollama tag runs past it easily, and the name must not touch its role.
    long_default = "hf.co/empero-ai/Qwen3.8-9B-Distill-GGUF:Q5_K_M-and-then-some"
    _serving(
        monkeypatch,
        {
            ("ollama", "http://localhost:11434"): (
                "qwen3:32b",
                "llama3.2:3b",
                "spare:1b",
                long_default,
            )
        },
    )

    result = runner.invoke(app, ["config", "models"])

    assert result.exit_code == 0, result.output
    lines = {line.strip().split()[0]: line for line in result.stdout.splitlines() if line.strip()}
    assert "default" in lines["qwen3:32b"]
    assert "classifier" in lines["llama3.2:3b"]
    # Spoken for by nobody: exactly its own name, no trailing padding.
    assert lines["spare:1b"].strip() == "spare:1b"
    # ...and the long one stays a whole, copyable id.
    assert long_default in result.stdout


SHARED = """\
name: default
version: 1

providers:
  ollama:
    type: ollama
    base_url: http://localhost:11434

default:
  provider: ollama
  model: "qwen3:32b"

roles:
  classifier:
    provider: ollama
    model: "llama3.2:3b"
  writer:
    provider: ollama
    model: "llama3.2:3b"
"""


def test_config_models_names_every_role_a_shared_model_answers_for(tmp_path, monkeypatch):
    """One model may be pointed at by several roles, and the list has to say so.

    Inverting role -> model one-to-one keeps whichever role sorted last and
    drops the rest, so a reader looking for `classifier` was told the model it
    is on belongs to `writer` -- and rebinding one of them looked safe.
    """
    _project(tmp_path, SHARED)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, {("ollama", "http://localhost:11434"): ("qwen3:32b", "llama3.2:3b")})

    result = runner.invoke(app, ["config", "models"])

    assert result.exit_code == 0, result.output
    shared = next(line for line in result.stdout.splitlines() if "llama3.2:3b" in line)
    assert "classifier" in shared
    assert "writer" in shared


def test_config_models_reports_an_endpoint_it_cannot_reach(tmp_path, monkeypatch):
    """A laptop with Ollama switched off is the normal case, not a failure."""
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, {("anthropic", None): ("claude-opus-5",)})

    result = runner.invoke(app, ["config", "models"])

    assert result.exit_code == 0, result.output
    assert "claude-opus-5" in result.stdout
    # Named, and said to be silent -- not quietly dropped from the listing.
    assert "ollama" in result.stdout
    assert "no answer" in result.stdout


def test_config_models_survives_a_provider_with_nothing_to_ask(tmp_path, monkeypatch):
    """`mock` answers from its own file. There is nothing to list, and that is
    an answer rather than a crash."""
    _project(
        tmp_path,
        'name: m\nversion: 1\nproviders:\n  fake: {type: mock}\ndefault: {provider: fake, model: "mock-model"}\n',
    )
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, {})

    result = runner.invoke(app, ["config", "models"])

    assert result.exit_code == 0, result.output
    assert "fake" in result.stdout


def test_config_models_json_carries_the_live_lists(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, {("ollama", "http://localhost:11434"): ("qwen3:32b", "llama3.2:3b")})

    result = runner.invoke(app, ["config", "models", "--json"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["ollama"]["models"] == ["qwen3:32b", "llama3.2:3b"]
    assert report["ollama"]["reachable"] is True
    assert report["claude"]["reachable"] is False


def test_config_models_asks_every_provider_at_once(tmp_path, monkeypatch):
    """Two endpoints asked in single file is two timeouts on a laptop where
    neither is running, and this command is read one screen at a time."""
    import asyncio

    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    in_flight, peak_in_flight = 0, 0
    both_probes_started = asyncio.Event()

    async def models_for(type_, base_url=None, api_key_env=None):
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        if in_flight == 2:
            both_probes_started.set()
        try:
            await asyncio.wait_for(both_probes_started.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass  # a sequential implementation reaches the assertion below
        finally:
            in_flight -= 1
        return ()

    monkeypatch.setattr(detect_module, "models_for", models_for)

    assert runner.invoke(app, ["config", "models"]).exit_code == 0
    assert peak_in_flight == 2, "providers were probed one after another"


@pytest.mark.parametrize("argv", [["config"], ["config", "models"]])
def test_config_never_writes_anything(tmp_path, monkeypatch, argv):
    """The read half. Changing what a project is bound to is `config use`."""
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, {("ollama", "http://localhost:11434"): ("qwen3:32b",)})

    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert runner.invoke(app, argv).exit_code == 0
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
