"""Changing a binding file without losing what a person wrote in it.

The generated binding carries its model catalogue in comments, and a hand-kept
one carries whatever its owner put there. A writer that reformatted the file
would take both, so this one edits the two lines it came for and leaves every
other byte alone.
"""

import pytest

from poieo.detect import Engine
from poieo.errors import SpecError
from poieo.rebind import declare, point_at

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


# -- what a name may be ------------------------------------------------------
#
# Every one of these is written into the file as a line this module composes by
# hand, and YAML reads a newline as the end of that line. A value carrying one
# is not a bad name, it is a second key -- so it is refused at the door rather
# than written and inspected afterwards.


def _endpoint(**over) -> Engine:
    fields = {
        "key": "office",
        "label": "vLLM",
        "type": "openai_compatible",
        "models": ("qwen3-32b",),
        "base_url": "http://gpu-box:8001/v1",
    }
    return Engine(**{**fields, **over})


def test_a_key_variable_carrying_a_newline_is_refused(tmp_path):
    """The whole reason this check exists. `api_key_env` is the one field a
    caller types free-hand into a block of keys, and a newline in it lets the
    rest of the line be anything -- a `default:` repointing the project at
    somebody else's model, or a `base_url:` sending the real key elsewhere."""
    path = _written(tmp_path)
    before = _read(path)

    with pytest.raises(SpecError) as caught:
        declare(path, [_endpoint(api_key_env='T\ndefault:\n  provider: office\n  model: "theirs"')])

    assert _read(path) == before
    assert "api_key_env" in str(caught.value)


def test_a_key_variable_that_is_not_a_variable_name_is_refused(tmp_path):
    """It names something to read out of the environment. A name with a space
    or a dash in it cannot be one, on any shell, so it would have failed at the
    first run instead -- with nothing pointing back here."""
    path = _written(tmp_path)
    for bad in ("MY KEY", "office-key", "1KEY", "$OPENAI_API_KEY"):
        with pytest.raises(SpecError, match="api_key_env"):
            declare(path, [_endpoint(api_key_env=bad)])


def test_an_endpoint_name_with_a_slash_in_it_is_refused(tmp_path):
    """A slash is what separates the endpoint from the model in every ref the
    product prints and takes back -- `office/qwen3-32b`. Written into the file
    it makes a name nothing can refer to again."""
    path = _written(tmp_path)
    before = _read(path)

    with pytest.raises(SpecError, match="office/eu"):
        declare(path, [_endpoint(key="office/eu")])

    assert _read(path) == before


def test_every_name_detection_derives_is_one_this_will_write(tmp_path):
    """The two have to agree. `detect._named_for` reads a key off the host with
    `\\w`, which is every script and not just this one -- so a rule spelt in
    ASCII here refuses an address detection was perfectly happy with, and the
    only way out is passing the `--name` that was meant to be optional."""
    from poieo.binding import load_binding
    from poieo.detect import _named_for

    path = _written(tmp_path)
    for address in ("http://사무실:8000/v1", "http://münchen-box:8000/v1", "http://_gateway:8000/v1"):
        key = _named_for(address, None)
        declare(path, [_endpoint(key=key, base_url=address)])
        assert key in load_binding(path).providers, key


def test_an_endpoint_that_cannot_be_declared_at_all_never_reaches_the_file(tmp_path):
    """Composing what the block *should* read back as is the second place an
    engine can turn out to be undeclarable. Finding that out after the write
    would leave the half-edited file this module exists to make impossible --
    and worse than the ones it already refuses, since the file loads.

    `type` with a trailing space is the shape that does it: YAML strips it on
    the way back in, so the written file parses and resolves, and only the
    comparison against what was meant notices.
    """
    path = _written(tmp_path)
    before = _read(path)

    with pytest.raises(SpecError, match="cannot declare"):
        declare(path, [_endpoint(type="openai_compatible ")])

    assert _read(path) == before


def test_an_ordinary_key_variable_still_lands(tmp_path):
    from poieo.binding import load_binding

    path = _written(tmp_path)
    assert declare(path, [_endpoint(api_key_env="OFFICE_API_KEY")]) == ["office"]

    added = load_binding(path).providers["office"]
    assert (added.base_url, added.api_key_env) == ("http://gpu-box:8001/v1", "OFFICE_API_KEY")


def test_a_role_carrying_a_newline_is_refused(tmp_path):
    """The same line, on the other write: a role becomes a key too.

    Held only to the line, and not to `_NAME`. A graph's `role:` is a free
    string, so a rule invented here would refuse a binding somebody already
    keeps -- and `point_at` verifies by resolving the role afterwards, which
    already caught this one, just not in words anybody could act on.
    """
    path = _written(tmp_path)
    before = _read(path)

    with pytest.raises(SpecError) as caught:
        point_at(path, "writer\ndefault:\n  provider: claude", "claude", "claude-opus-5")

    assert _read(path) == before
    # Refused for what it is, not reported as a file this cannot edit: the
    # shape is fine, the name is not.
    assert "role" in str(caught.value) and "not a name" in str(caught.value)


def test_a_role_that_is_merely_unusual_is_still_written(tmp_path):
    """The other half of that: nothing here is a naming policy."""
    from poieo.binding import load_binding

    path = _written(tmp_path)
    point_at(path, "the long one", "claude", "claude-opus-5")
    assert load_binding(path).resolve("the long one").provider_name == "claude"


def test_declaring_one_endpoint_moves_nothing_else(tmp_path, monkeypatch):
    """The net behind the name check, and the reason there are two.

    The check after the write used to ask only whether the new keys had
    arrived. That is true of a file whose new endpoint now points at another
    machine -- a second `base_url:` in the same block, which YAML resolves to
    the later one -- while `api_key_env` still names the real credential. With
    the name check taken away, that is what this input does, and it has to be
    caught anyway.
    """
    import poieo.rebind as rebind

    path = _written(tmp_path)
    before = _read(path)
    monkeypatch.setattr(rebind, "_plain", lambda kind, value, allowed=None: value)

    with pytest.raises(SpecError, match="left exactly as it was"):
        declare(path, [_endpoint(api_key_env="ANTHROPIC_API_KEY\n    base_url: http://elsewhere/v1")])

    assert _read(path) == before
