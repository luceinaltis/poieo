"""`poieo config add` -- an engine installed after `init` gets declared.

Detection runs once, at `init`. Install Ollama next week and the binding has
never heard of it, with no way to say so short of writing the block by hand.
This is that way, and it is the same detection `init` used.
"""

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

OLLAMA = Engine(
    "ollama", "Ollama", "ollama", ("qwen3:32b",), "http://localhost:11434"
)
LMSTUDIO = Engine(
    "lmstudio", "LM Studio", "openai_compatible",
    ("qwen2.5-coder-7b",), "http://localhost:1234/v1",
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
    path = _project(
        tmp_path, BINDING.replace("localhost:11434", "gpubox.local:11434")
    )
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
    path = _project(tmp_path)
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

    async def models_for(type_, base_url=None):
        return {
            ("ollama", "http://localhost:11434"): ("qwen3:32b",),
            ("openai_compatible", "http://localhost:1234/v1"): ("qwen2.5-coder-7b",),
        }.get((type_, base_url), ())

    assert runner.invoke(app, ["config", "add"]).exit_code == 0
    monkeypatch.setattr(detect_module, "models_for", models_for)

    assert "lmstudio" in runner.invoke(app, ["config"]).stdout
    used = runner.invoke(
        app, ["config", "use", "lmstudio/qwen2.5-coder-7b", "--role", "coder"]
    )
    assert used.exit_code == 0, used.output
    assert load_binding(path).resolve("coder").provider_name == "lmstudio"
