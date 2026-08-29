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


def test_a_model_can_say_how_much_it_can_hold():
    """How much a model can hold is a fact about the model, so it belongs on
    the physical half of the binding rather than in a constant somewhere.

    Measured, the difference is not small: `z-ai/glm-5.3-flash` holds
    1,310,720 tokens and a local qwen3.5 holds 262,144. Anything hardcoded is
    wrong for one of them by design.
    """
    binding = BindingSpec.model_validate(
        {
            "providers": {"p": {"type": "mock"}},
            "default": {"provider": "p", "model": "small", "context": 32_000},
            "roles": {"builder": {"model": "big", "context": 1_310_720}},
        }
    )

    assert binding.resolve("builder").context == 1_310_720
    assert binding.resolve("anything").context == 32_000


def test_a_binding_that_says_nothing_about_size_says_nothing():
    """None is not a number to work around -- it means "ask somewhere else",
    and the caller decides what to do about that."""
    binding = BindingSpec.model_validate(
        {"providers": {"p": {"type": "mock"}}, "default": {"provider": "p", "model": "m"}}
    )
    assert binding.resolve("anything").context is None


def test_context_is_not_sent_to_the_model():
    """It describes the endpoint; it is not a generation parameter. Putting it
    in `params` would post it in the request body, where a strict API rejects
    what it does not recognise."""
    binding = BindingSpec.model_validate(
        {
            "providers": {"p": {"type": "mock"}},
            "default": {"provider": "p", "model": "m", "context": 200_000},
        }
    )
    assert "context" not in binding.resolve("anything").params


def test_a_model_can_say_what_it_charges():
    """For an endpoint that bills and does not say so.

    OpenRouter answers with `cost` when asked; Anthropic's API does not carry
    one at all, and it is the paid backend this project ships an example for.
    Somebody who wants a spend limit there has to be able to write the prices
    down, and beside `model` for the same reason `context` is: it describes
    the endpoint rather than asking it for anything.
    """
    binding = BindingSpec.model_validate(
        {
            "providers": {"p": {"type": "mock"}},
            "default": {
                "provider": "p",
                "model": "m",
                "prices": {"input": 5.0, "output": 25.0, "cache_read": 0.5},
            },
        }
    )

    prices = binding.resolve("anything").prices
    assert prices is not None
    assert prices.input == 5.0 and prices.output == 25.0 and prices.cache_read == 0.5


def test_a_binding_that_says_nothing_about_price_says_nothing():
    """None means nobody has said, which a spend limit has to treat as "cannot
    be enforced" rather than as free."""
    binding = BindingSpec.model_validate(
        {"providers": {"p": {"type": "mock"}}, "default": {"provider": "p", "model": "m"}}
    )
    assert binding.resolve("anything").prices is None


def test_prices_are_not_sent_to_the_model():
    binding = BindingSpec.model_validate(
        {
            "providers": {"p": {"type": "mock"}},
            "default": {"provider": "p", "model": "m", "prices": {"input": 1.0}},
        }
    )
    assert "prices" not in binding.resolve("anything").params


def test_what_a_call_cost_is_worked_out_per_million_tokens():
    """The unit every vendor quotes in, so the number in a binding is the
    number on the pricing page rather than one somebody converted by hand and
    got wrong by six zeroes."""
    from poieo.binding import Prices
    from poieo.providers.base import Usage

    prices = Prices(input=5.0, output=25.0, cache_read=0.5)
    # A million uncached in, a million out: five dollars and twenty-five.
    assert prices.charge(Usage(input_tokens=1_000_000, output_tokens=1_000_000)) == 30.0
    # Cached input is charged at the cache rate, not the input one.
    spent = prices.charge(Usage(input_tokens=1_000_000, cache_read_tokens=1_000_000, output_tokens=0))
    assert spent == 0.5


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
    binding = BindingSpec.model_validate({"providers": {"p": {"type": "mock"}}, "default": {"provider": "p"}})
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
