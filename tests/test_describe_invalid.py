"""A typo in a YAML file reads in the user's words, not pydantic's.

Every spec loader in the package -- graph, task, binding, project, daemon --
runs its validation failure through `describe_invalid`. These tests are about
the function itself; the loaders' own tests check that each one calls it.
"""

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from poieo.errors import describe_invalid


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = ""


class Outer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    inner: list[Inner] = []


KEYS = tuple(Outer.model_fields) + tuple(Inner.model_fields)


def _invalid(data) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        Outer.model_validate(data)
    return caught.value


def test_an_unknown_key_is_named_and_a_near_miss_suggested():
    said = describe_invalid(_invalid({"name": "x", "nmae": "x"}), KEYS)
    assert "'nmae' is not a setting here -- did you mean 'name'?" in said


def test_a_nested_typo_still_gets_its_suggestion():
    """The key arrives dotted -- `inner.0.promt` -- and a reader who typed
    `promt` wants the same help they would get at the top level."""
    said = describe_invalid(_invalid({"name": "x", "inner": [{"promt": "hi"}]}), KEYS)
    assert "'inner.0.promt' is not a setting here -- did you mean 'prompt'?" in said


def test_a_key_that_resembles_nothing_gets_no_guess():
    said = describe_invalid(_invalid({"name": "x", "zzzzzzzz": 1}), KEYS)
    assert "'zzzzzzzz' is not a setting here" in said
    assert "did you mean" not in said


def test_a_missing_key_says_so():
    assert "'name' is required" in describe_invalid(_invalid({}), KEYS)


def test_every_problem_gets_a_line():
    said = describe_invalid(_invalid({"nmae": "x", "extra": 1}), KEYS)
    assert said.count(";") == 2  # missing name, plus the two unknown keys


def test_pydantic_is_never_quoted_at_the_user():
    said = describe_invalid(_invalid({"name": "x", "nmae": "x"}), KEYS)
    assert "errors.pydantic.dev" not in said
    assert "extra_forbidden" not in said


def test_something_that_is_not_a_validation_error_falls_back_to_its_own_words():
    assert describe_invalid(ValueError("plain trouble")) == "plain trouble"
