"""`poieo config use` -- the one command that changes which model answers.

Everything it does is one edit to one file. What it refuses to do is most of
the design: an undeclared provider, a model the endpoint says it does not
serve, and any shape it cannot edit cleanly.
"""

import json

from typer.testing import CliRunner

from poieo import detect as detect_module
from poieo.binding import load_binding
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

# What each engine had when this file was written:
#   ollama  qwen3:32b  llama3.2:3b
"""


def _project(tmp_path, binding: str = BINDING):
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models" / "default.yaml").write_text(binding, encoding="utf-8")
    (tmp_path / "tasks").mkdir(exist_ok=True)
    (tmp_path / "poieo.yaml").write_text(
        "version: 1\nstore: runs\nbinding: models/default.yaml\ntasks: tasks/\n",
        encoding="utf-8",
    )
    return tmp_path / "models" / "default.yaml"


def _serving(monkeypatch, answers):
    async def models_for(type_, base_url=None, api_key_env=None):
        return answers.get((type_, base_url), ())

    monkeypatch.setattr(detect_module, "models_for", models_for)


OLLAMA_HAS = {
    ("ollama", "http://localhost:11434"): ("qwen3:32b", "llama3.2:3b"),
    ("anthropic", None): ("claude-opus-5",),
}


def test_use_moves_the_default(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, OLLAMA_HAS)

    result = runner.invoke(app, ["config", "use", "ollama/llama3.2:3b"])

    assert result.exit_code == 0, result.output
    assert load_binding(path).resolve("default").model == "llama3.2:3b"
    # Says what moved, and where the edit landed.
    assert "llama3.2:3b" in result.stdout and "default.yaml" in result.stdout


def test_use_with_a_role_binds_that_role_only(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, OLLAMA_HAS)

    result = runner.invoke(app, ["config", "use", "claude/claude-opus-5", "--role", "critic"])

    assert result.exit_code == 0, result.output
    spec = load_binding(path)
    assert spec.resolve("critic").provider_name == "claude"
    assert spec.resolve("default").model == "qwen3:32b"  # untouched


def test_use_keeps_the_comments_the_file_came_with(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, OLLAMA_HAS)

    assert runner.invoke(app, ["config", "use", "ollama/llama3.2:3b"]).exit_code == 0

    after = path.read_text(encoding="utf-8")
    assert "# What each engine had when this file was written:" in after
    assert "max_tokens: 2048" in after


def test_an_undeclared_provider_is_refused(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, OLLAMA_HAS)
    before = path.read_text(encoding="utf-8")

    result = runner.invoke(app, ["config", "use", "lmstudio/whatever"])

    assert result.exit_code == 1
    assert "lmstudio" in result.stderr
    assert path.read_text(encoding="utf-8") == before


def test_a_model_the_endpoint_does_not_serve_is_refused(tmp_path, monkeypatch):
    """The typo this whole feature exists to prevent. A model named from
    memory does not fail here -- it fails at 3am, in a run."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, OLLAMA_HAS)
    before = path.read_text(encoding="utf-8")

    result = runner.invoke(app, ["config", "use", "ollama/qwen3:32-b"])

    assert result.exit_code == 1
    # Names what it does serve, so the fix is in the refusal.
    assert "qwen3:32b" in result.stderr
    assert path.read_text(encoding="utf-8") == before


def test_an_unreachable_endpoint_does_not_block_the_edit(tmp_path, monkeypatch):
    """A laptop with Ollama switched off still gets to edit its own config.
    Checking is best-effort; silence is not a verdict."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, {})

    result = runner.invoke(app, ["config", "use", "ollama/anything-at-all"])

    assert result.exit_code == 0, result.output
    assert load_binding(path).resolve("default").model == "anything-at-all"
    # ...but says it could not check, rather than implying it did.
    assert "could not" in result.stdout.lower() or "no answer" in result.stdout.lower()


def test_a_reference_without_a_slash_is_refused_in_the_products_voice(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, OLLAMA_HAS)

    result = runner.invoke(app, ["config", "use", "qwen3:32b"])

    assert result.exit_code == 1
    assert "provider/model" in result.stderr


def test_a_model_id_full_of_slashes_still_splits_once(tmp_path, monkeypatch):
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    hairy = "hf.co/empero-ai/Qwen3.8-9B-Distill-GGUF:Q5_K_M"
    _serving(monkeypatch, {("ollama", "http://localhost:11434"): (hairy,)})

    result = runner.invoke(app, ["config", "use", f"ollama/{hairy}"])

    assert result.exit_code == 0, result.output
    assert load_binding(path).resolve("default").model == hairy


def test_what_config_prints_is_what_use_takes_back(tmp_path, monkeypatch):
    """The round trip that makes the pair usable: copy a line out of one
    command, paste it into the other."""
    path = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    _serving(monkeypatch, OLLAMA_HAS)

    shown = json.loads(runner.invoke(app, ["config", "--json"]).stdout)["default"]
    assert runner.invoke(app, ["config", "use", shown]).exit_code == 0

    assert load_binding(path).resolve("default").model == "qwen3:32b"
