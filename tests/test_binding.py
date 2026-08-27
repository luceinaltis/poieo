import pytest

from conftest import EXAMPLES
from poieo.binding import BindingSpec, load_binding
from poieo.errors import BindingError


def test_role_overrides_layer_over_default():
    binding = load_binding(EXAMPLES / "models/claude.yaml")
    classifier = binding.resolve("classifier")
    writer = binding.resolve("writer")

    # Inherited from `default`.
    assert classifier.provider_name == "claude"
    # Overridden per role.
    assert classifier.model == "claude-haiku-4-5"
    assert classifier.params["max_tokens"] == 256
    # Params merge key-by-key rather than replacing the whole block.
    assert classifier.params["effort"] == "high"
    assert writer.params["effort"] == "medium"


def test_unknown_role_falls_back_to_default():
    binding = load_binding(EXAMPLES / "models/claude.yaml")
    assert binding.resolve("anything").model == "claude-opus-5"


def test_node_overrides_win_over_binding():
    binding = load_binding(EXAMPLES / "models/claude.yaml")
    resolved = binding.resolve("writer", {"max_tokens": 42})
    assert resolved.params["max_tokens"] == 42


def test_hybrid_binding_splits_roles_across_providers():
    binding = load_binding(EXAMPLES / "models/hybrid.yaml")
    assert binding.resolve("classifier").provider_name == "ollama"
    assert binding.resolve("writer").provider_name == "claude"


def test_missing_model_is_reported():
    binding = BindingSpec.model_validate(
        {"providers": {"p": {"type": "mock"}}, "default": {"provider": "p"}}
    )
    with pytest.raises(BindingError, match="no model id"):
        binding.resolve("writer")


def test_undeclared_provider_is_rejected():
    with pytest.raises(Exception, match="undeclared provider"):
        BindingSpec.model_validate(
            {
                "providers": {"p": {"type": "mock"}},
                "roles": {"writer": {"provider": "ghost", "model": "m"}},
            }
        )


def test_local_providers_require_a_base_url():
    with pytest.raises(Exception, match="requires a base_url"):
        BindingSpec.model_validate({"providers": {"p": {"type": "ollama"}}})


def test_check_roles_lists_only_unsatisfiable_ones():
    binding = BindingSpec.model_validate({"providers": {"p": {"type": "mock"}}})
    assert binding.check_roles({"writer", "critic"}) == ["critic", "writer"]


def test_a_role_the_binding_never_names_is_reportable(tmp_path):
    """`resolve` falls back to the default for any role at all, which is the
    point of having one -- and the reason check_roles can never report a typo.
    This is the question that can: which of these did the binding declare?"""
    binding = BindingSpec.model_validate(
        {
            "name": "b",
            "providers": {"p": {"type": "mock"}},
            "default": {"provider": "p", "model": "big"},
            "roles": {"classifier": {"model": "small"}},
        }
    )

    assert binding.undeclared({"classifier", "classifer", "writer"}) == [
        "classifer",
        "writer",
    ]
    assert binding.undeclared({"classifier"}) == []
    # It still resolves -- that is exactly the quiet part.
    assert binding.resolve("classifer").model == "big"
