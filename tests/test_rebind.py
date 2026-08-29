"""Changing a binding file without losing what a person wrote in it.

The generated binding carries its model catalogue in comments, and a hand-kept
one carries whatever its owner put there. A writer that reformatted the file
would take both, so this one edits the two lines it came for and leaves every
other byte alone.
"""

import pytest

from poieo.errors import SpecError
from poieo.rebind import point_at

GENERATED = """\
# Physical layer: every engine this machine answered on when
# `poieo init` looked. A graph names a role; a role names a model here.
#
# Detection does not run again -- edit this file freely.
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
  model: "a:1"
  params:
    max_tokens: 2048

# Give a role its own model, and a graph that names that role uses it:
#
#   roles:
#     classifier:
#       provider: claude
#       model: "claude-opus-5"
#
# What each engine had when this file was written:
#   ollama  a:1  b:2
#   claude  claude-opus-5
"""


def _written(tmp_path, body=GENERATED):
    path = tmp_path / "default.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _read(path):
    return path.read_text(encoding="utf-8")


# -- the default -------------------------------------------------------------


def test_pointing_the_default_somewhere_else(tmp_path):
    path = _written(tmp_path)
    point_at(path, "default", "claude", "claude-opus-5")

    from poieo.binding import load_binding

    resolved = load_binding(path).resolve("default")
    assert (resolved.provider_name, resolved.model) == ("claude", "claude-opus-5")


def test_everything_the_person_wrote_survives(tmp_path):
    """The catalogue, the header, the worked example -- all comments, all the
    reason the file is worth keeping rather than regenerating."""
    path = _written(tmp_path)
    point_at(path, "default", "claude", "claude-opus-5")
    after = _read(path)

    for kept in (
        "# Detection does not run again -- edit this file freely.",
        "#     classifier:",
        "# What each engine had when this file was written:",
        "#   ollama  a:1  b:2",
        "base_url: http://localhost:11434",
        "max_tokens: 2048",  # params under `default:` are not ours to touch
    ):
        assert kept in after, kept


def test_only_the_two_lines_it_came_for_change(tmp_path):
    path = _written(tmp_path)
    before = _read(path).splitlines()
    point_at(path, "default", "claude", "claude-opus-5")
    after = _read(path).splitlines()

    assert len(before) == len(after)
    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 2, [after[i] for i in differing]


def test_a_model_id_full_of_punctuation_round_trips(tmp_path):
    from poieo.binding import load_binding

    path = _written(tmp_path)
    hairy = "hf.co/empero-ai/Qwen3.8-9B-Distill-GGUF:Q5_K_M"
    point_at(path, "default", "ollama", hairy)
    assert load_binding(path).resolve("default").model == hairy


# -- roles -------------------------------------------------------------------


def test_a_first_role_brings_the_roles_block_with_it(tmp_path):
    """The generated file has no `roles:` key at all -- only a comment showing
    one. Naming a role has to make the block, not assume it."""
    from poieo.binding import load_binding

    path = _written(tmp_path)
    point_at(path, "classifier", "claude", "claude-opus-5")

    spec = load_binding(path)
    assert spec.resolve("classifier").provider_name == "claude"
    # ...and the default is untouched.
    assert spec.resolve("default").model == "a:1"


def test_a_second_role_joins_the_first(tmp_path):
    from poieo.binding import load_binding

    path = _written(tmp_path)
    point_at(path, "classifier", "claude", "claude-opus-5")
    point_at(path, "writer", "ollama", "b:2")

    spec = load_binding(path)
    assert spec.resolve("classifier").provider_name == "claude"
    assert spec.resolve("writer").model == "b:2"


def test_pointing_a_role_that_already_exists_moves_it(tmp_path):
    from poieo.binding import load_binding

    path = _written(tmp_path)
    point_at(path, "classifier", "claude", "claude-opus-5")
    point_at(path, "classifier", "ollama", "b:2")

    spec = load_binding(path)
    assert spec.resolve("classifier").provider_name == "ollama"
    assert spec.resolve("classifier").model == "b:2"
    # Moved, not duplicated: a second entry would be a silent shadow, and
    # YAML would quietly let the later one win. Counted on real lines, not on
    # the substring -- the file's own worked example is a comment saying
    # `classifier:` too.
    entries = [
        line for line in _read(path).splitlines() if line.strip() == "classifier:" and not line.lstrip().startswith("#")
    ]
    assert len(entries) == 1


def test_a_roles_block_a_person_already_wrote_is_added_to(tmp_path):
    from poieo.binding import load_binding

    path = _written(
        tmp_path,
        GENERATED.replace(
            "# Give a role",
            'roles:\n  writer:\n    provider: ollama\n    model: "b:2"\n\n# Give a role',
        ),
    )
    point_at(path, "classifier", "claude", "claude-opus-5")

    spec = load_binding(path)
    assert spec.resolve("writer").model == "b:2"
    assert spec.resolve("classifier").provider_name == "claude"


def test_a_roles_entry_keeps_its_own_params(tmp_path):
    """Someone tuned this role. Repointing its model must not undo that."""
    from poieo.binding import load_binding

    path = _written(
        tmp_path,
        GENERATED + 'roles:\n  writer:\n    provider: ollama\n    model: "b:2"\n    params:\n      temperature: 0\n',
    )
    point_at(path, "writer", "claude", "claude-opus-5")

    spec = load_binding(path)
    assert spec.resolve("writer").model == "claude-opus-5"
    assert spec.resolve("writer").params["temperature"] == 0


# -- refusing, rather than mangling ------------------------------------------


def test_an_undeclared_provider_is_refused_before_anything_is_written(tmp_path):
    path = _written(tmp_path)
    before = _read(path)

    with pytest.raises(SpecError, match="lmstudio"):
        point_at(path, "default", "lmstudio", "whatever")

    assert _read(path) == before


def test_a_shape_it_cannot_edit_is_refused_with_the_line_to_change(tmp_path):
    """Flow-style YAML is legal and rare, and guessing at it is how a config
    file gets quietly corrupted. Say what to edit and stop."""
    path = _written(
        tmp_path,
        "name: d\nversion: 1\nproviders: {ollama: {type: ollama, "
        "base_url: 'http://x'}}\ndefault: {provider: ollama, model: 'a:1'}\n",
    )
    before = _read(path)

    with pytest.raises(SpecError) as caught:
        point_at(path, "default", "ollama", "b:2")

    assert _read(path) == before
    said = str(caught.value)
    assert "default" in said and str(path) in said


def test_an_edit_that_would_not_load_puts_the_file_back(tmp_path, monkeypatch):
    """The safety net: surgery is verified by reloading, and a file that no
    longer parses -- or no longer resolves the way it was asked to -- is
    restored rather than left on disk."""
    import poieo.rebind as rebind

    path = _written(tmp_path)
    before = _read(path)
    monkeypatch.setattr(rebind, "_repoint", lambda *a, **k: "nonsense: [unclosed\n")

    with pytest.raises(SpecError):
        point_at(path, "default", "claude", "claude-opus-5")

    assert _read(path) == before
