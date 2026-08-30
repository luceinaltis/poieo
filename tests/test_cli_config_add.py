"""`poieo config add` -- an engine installed after `init` gets declared.

Detection runs once, at `init`. Install Ollama next week and the binding has
never heard of it, with no way to say so short of writing the block by hand.
This is that way, and it is the same detection `init` used.
"""

import os
from dataclasses import replace

from typer.testing import CliRunner

from poieo import detect as detect_module
from poieo.binding import load_binding
from poieo.cli import app
from poieo.detect import Engine

runner = CliRunner()

BINDING = """\
# Physical layer: every engine this machine answered on when
# `poieo init` looked.
name: default
version: 1

providers:
  ollama:
    type: ollama
    base_url: http://localhost:11434

default:
  provider: ollama
  model: "qwen3:32b"
  params:
    max_tokens: 2048

# What each engine had when this file was written:
#   ollama  qwen3:32b
"""

OLLAMA = Engine("ollama", "Ollama", "ollama", ("qwen3:32b",), "http://localhost:11434")
LMSTUDIO = Engine(
    "lmstudio",
    "LM Studio",
    "openai_compatible",
    ("qwen2.5-coder-7b",),
    "http://localhost:1234/v1",
)
CLAUDE = Engine("claude", "Claude API", "anthropic", ("claude-opus-5",))


def _project(tmp_path, binding: str = BINDING):
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models" / "default.yaml").write_text(binding, encoding="utf-8")
    (tmp_path / "tasks").mkdir(exist_ok=True)
    (tmp_path / "poieo.yaml").write_text(
        "version: 1\nstore: runs\nbinding: models/default.yaml\ntasks: tasks/\n",
        encoding="utf-8",
    )
    return tmp_path / "models" / "default.yaml"


def _machine_with(monkeypatch, *engines):
    monkeypatch.setattr(detect_module, "detect", lambda: list(engines))


def test_a_newly_installed_engine_is_declared(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, LMSTUDIO)

    result = runner.invoke(app, ["config", "add"])

    assert result.exit_code == 0, result.output
    spec = load_binding(path)
    assert set(spec.providers) == {"ollama", "lmstudio"}
    assert spec.providers["lmstudio"].type == "openai_compatible"
    assert spec.providers["lmstudio"].base_url == "http://localhost:1234/v1"
    assert "lmstudio" in result.stdout


def test_an_engine_with_no_address_is_declared_without_one(tmp_path, monkeypatch):
    """Claude's SDK knows where it lives; a base_url would be a wrong guess."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, CLAUDE)

    assert runner.invoke(app, ["config", "add"]).exit_code == 0

    declared = load_binding(path).providers["claude"]
    assert declared.type == "anthropic"
    assert declared.base_url is None


def test_what_is_already_declared_is_left_exactly_alone(tmp_path, monkeypatch):
    """Somebody may have pointed ollama at another port, or tuned it. Adding
    is adding; it is not a second round of `init`."""
    path = _project(tmp_path, BINDING.replace("localhost:11434", "gpubox.local:11434"))
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, LMSTUDIO)

    assert runner.invoke(app, ["config", "add"]).exit_code == 0

    spec = load_binding(path)
    assert spec.providers["ollama"].base_url == "http://gpubox.local:11434"


def test_the_default_is_never_moved(tmp_path, monkeypatch):
    """`add` declares; `use` chooses. A command that quietly repointed the
    default would change what runs tonight."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, LMSTUDIO, OLLAMA)  # lmstudio detected first

    assert runner.invoke(app, ["config", "add"]).exit_code == 0

    resolved = load_binding(path).resolve("default")
    assert (resolved.provider_name, resolved.model) == ("ollama", "qwen3:32b")


def test_nothing_new_is_said_so_and_changes_nothing(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA)
    before = path.read_text(encoding="utf-8")

    result = runner.invoke(app, ["config", "add"])

    assert result.exit_code == 0, result.output
    assert path.read_text(encoding="utf-8") == before
    assert "nothing new" in result.stdout.lower()


def test_the_comments_the_file_came_with_survive(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, LMSTUDIO)

    assert runner.invoke(app, ["config", "add"]).exit_code == 0

    after = path.read_text(encoding="utf-8")
    assert "# `poieo init` looked." in after
    assert "# What each engine had when this file was written:" in after
    assert "max_tokens: 2048" in after


def test_it_says_what_the_new_engine_serves(tmp_path, monkeypatch):
    """The point of declaring one is naming a model on it, so the models it
    has belong in the same breath."""
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, LMSTUDIO)

    result = runner.invoke(app, ["config", "add"])

    assert "qwen2.5-coder-7b" in result.stdout
    # ...and points at the command that would use it.
    assert "config use" in result.stdout


def test_a_machine_with_nothing_answering_says_so(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch)
    before = path.read_text(encoding="utf-8")

    result = runner.invoke(app, ["config", "add"])

    assert result.exit_code == 0, result.output
    assert path.read_text(encoding="utf-8") == before


def test_added_engines_show_up_in_config_and_are_usable(tmp_path, monkeypatch):
    """The whole round trip: add it, see it, bind a role to it."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, LMSTUDIO)

    async def models_for(type_, base_url=None, api_key_env=None):
        return {
            ("ollama", "http://localhost:11434"): ("qwen3:32b",),
            ("openai_compatible", "http://localhost:1234/v1"): ("qwen2.5-coder-7b",),
        }.get((type_, base_url), ())

    assert runner.invoke(app, ["config", "add"]).exit_code == 0
    monkeypatch.setattr(detect_module, "models_for", models_for)

    assert "lmstudio" in runner.invoke(app, ["config"]).stdout
    used = runner.invoke(app, ["config", "use", "lmstudio/qwen2.5-coder-7b", "--role", "coder"])
    assert used.exit_code == 0, used.output
    assert load_binding(path).resolve("coder").provider_name == "lmstudio"


# vLLM and SGLang default to the same port, so `CANDIDATES` can only ever call
# that address the pair. Which one is really there is a thing the server says
# about itself on its own listing, and having asked, this must not go back to
# printing the pair -- or reading the name out of the binding, which is what
# its author believed rather than what answered.
SGLANG = Engine(
    "vllm",
    "vLLM / SGLang",
    "openai_compatible",
    ("qwen3-32b",),
    "http://localhost:8000/v1",
    said="SGLang",
)


def test_a_server_that_named_itself_is_called_that_and_not_the_pair(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, SGLANG)

    result = runner.invoke(app, ["config", "add"])

    assert result.exit_code == 0, result.output
    assert "SGLang" in result.stdout
    assert "vLLM / SGLang" not in result.stdout


def test_a_server_that_named_itself_is_called_that_when_there_is_nothing_new(tmp_path, monkeypatch):
    """The line that says where it looked has to name them the same way."""
    _project(
        tmp_path,
        BINDING.replace(
            "providers:\n", "providers:\n  vllm:\n    type: openai_compatible\n    base_url: http://localhost:8000/v1\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, SGLANG)

    result = runner.invoke(app, ["config", "add"])

    assert "nothing new" in result.stdout.lower()
    assert "SGLang" in result.stdout
    assert "vLLM / SGLang" not in result.stdout


# -- an engine at an address nobody guessed ----------------------------------
#
# Detection knows four ports on *this* machine. A vLLM on 8001, an Ollama on
# the desktop under the desk, a shared box in an office -- none of them were
# reachable except by opening the binding file and typing a block by hand.
#
# `poieo config add <url>` takes the address and asks what is there. The
# command's no-argument form is untouched: that one still looks at this machine.


def _at(monkeypatch, engine, wants: str | None = None):
    """`detect.ask`, stood in for.

    ``wants`` names the variable this endpoint refuses to list without -- what
    every hosted endpoint does, and what a vLLM started with `--api-key` does.
    It has to be both named *and* set, since that is when the real `ask` has a
    key to send; without one the address answers as though nothing were there,
    which is what a 401 means to detection. ``None`` is an endpoint that lists
    for anyone.
    """

    async def fake(base_url, key_env=None):
        if base_url != engine.base_url:
            return None
        if wants is not None and not (key_env == wants and os.environ.get(wants)):
            return None
        return replace(engine, api_key_env=key_env or None)

    monkeypatch.setattr(detect_module, "ask", fake)


OFFICE = Engine(
    "gpu-box",
    "gpu-box",
    "openai_compatible",
    ("qwen3-32b",),
    "http://gpu-box:8001/v1",
)


def test_an_address_is_asked_and_declared(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _at(monkeypatch, OFFICE)

    result = runner.invoke(app, ["config", "add", "http://gpu-box:8001/v1"])

    assert result.exit_code == 0, result.output
    declared = load_binding(path).providers
    assert declared["gpu-box"].type == "openai_compatible"
    assert declared["gpu-box"].base_url == "http://gpu-box:8001/v1"


def test_an_address_that_answers_with_nothing_is_refused_and_writes_nothing(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    before = path.read_text(encoding="utf-8")
    _at(monkeypatch, OFFICE)

    result = runner.invoke(app, ["config", "add", "http://nothing-here:9999"])

    assert result.exit_code != 0
    assert "nothing-here:9999" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_an_address_may_be_given_the_name_the_reader_wants(tmp_path, monkeypatch):
    """Two vLLMs is the ordinary case, and both would be called `vllm`."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _at(monkeypatch, OFFICE)

    result = runner.invoke(app, ["config", "add", "http://gpu-box:8001/v1", "--name", "office"])

    assert result.exit_code == 0, result.output
    assert "office" in load_binding(path).providers


def test_an_address_may_name_the_variable_its_key_comes_from(tmp_path, monkeypatch):
    """A hosted endpoint wants one. The **name** of the variable is not a
    secret and belongs in the file; the key itself never goes near it.

    And the endpoint here is the real shape of one: it lists nothing at all
    until the request carries the key. That is what OpenAI, Groq, Together and
    a vLLM behind `--api-key` all do, and asking without the key made them the
    one kind of endpoint `--key-env` could not add.
    """
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OFFICE_TOKEN", "sk-real")
    _at(monkeypatch, OFFICE, wants="OFFICE_TOKEN")

    result = runner.invoke(app, ["config", "add", "http://gpu-box:8001/v1", "--key-env", "OFFICE_TOKEN"])

    assert result.exit_code == 0, result.output
    assert load_binding(path).providers["gpu-box"].api_key_env == "OFFICE_TOKEN"


def test_the_same_endpoint_without_the_key_is_the_address_that_answered_nothing(tmp_path, monkeypatch):
    """The other half, and the reason the one above is not circular."""
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OFFICE_TOKEN", "sk-real")
    _at(monkeypatch, OFFICE, wants="OFFICE_TOKEN")

    result = runner.invoke(app, ["config", "add", "http://gpu-box:8001/v1"])

    assert result.exit_code != 0
    assert "nothing usable answered" in result.output


def test_an_address_that_answered_nothing_says_the_variable_was_empty_too(tmp_path, monkeypatch):
    """Left to detection this came back as "nothing usable answered at ..." --
    a true sentence about the wrong problem, and one that has the reader
    retyping an address that was right all along."""
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OFFICE_TOKEN", raising=False)
    _at(monkeypatch, OFFICE, wants="OFFICE_TOKEN")

    result = runner.invoke(app, ["config", "add", "http://gpu-box:8001/v1", "--key-env", "OFFICE_TOKEN"])

    assert result.exit_code != 0
    assert "OFFICE_TOKEN" in result.output and "not set" in result.output


def test_an_endpoint_that_lists_without_a_key_is_declared_with_the_name_anyway(tmp_path, monkeypatch):
    """An unset variable is not a precondition, and must not be one. The key
    routinely lives in the environment the daemon runs under rather than this
    shell, and writing its name into a file somebody commits is a whole reason
    to run this from here."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OFFICE_TOKEN", raising=False)
    _at(monkeypatch, OFFICE)  # lists for anyone

    result = runner.invoke(app, ["config", "add", "http://gpu-box:8001/v1", "--key-env", "OFFICE_TOKEN"])

    assert result.exit_code == 0, result.output
    assert load_binding(path).providers["gpu-box"].api_key_env == "OFFICE_TOKEN"


def test_naming_a_variable_with_no_address_says_which_is_missing(tmp_path, monkeypatch):
    """The four ports detection looks at on this machine are not endpoints a
    key opens, and there would be no saying which of them it was meant for. It
    used to be read only inside the `if url:` branch and dropped in silence."""
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OFFICE_TOKEN", "sk-real")
    _machine_with(monkeypatch, OLLAMA)

    result = runner.invoke(app, ["config", "add", "--key-env", "OFFICE_TOKEN"])

    assert result.exit_code != 0
    assert "address" in result.output


def test_a_name_already_in_the_file_is_refused_rather_than_overwritten(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    before = path.read_text(encoding="utf-8")
    _at(monkeypatch, OFFICE)

    result = runner.invoke(app, ["config", "add", "http://gpu-box:8001/v1", "--name", "ollama"])

    assert result.exit_code != 0
    assert "ollama" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_looking_at_this_machine_still_takes_no_argument(tmp_path, monkeypatch):
    """The form that existed before, unchanged."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _machine_with(monkeypatch, OLLAMA, LMSTUDIO)

    assert runner.invoke(app, ["config", "add"]).exit_code == 0
    assert "lmstudio" in load_binding(path).providers
