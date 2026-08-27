import pytest

from poieo.errors import ExpressionError
from poieo.expr import compile_expr, evaluate, render, wrap


@pytest.fixture
def scope():
    return wrap(
        {
            "input": {"text": "A BUG report", "tags": ["p1", "ui"]},
            "state": {"retries": 1},
            "review": {"approved": False},
            "category": "Bug",
            "run": {"path": ["a", "b", "a"]},
        }
    )


@pytest.mark.parametrize(
    "source,expected",
    [
        ("category.lower() == 'bug'", True),
        ("state.retries < 3 and not review.approved", True),
        ("'ui' in input.tags", True),
        ("len(input.tags)", 2),
        ("run.path.count('a') >= 2", True),
        ("input['text'][:1]", "A"),
        ("'yes' if state.retries else 'no'", "yes"),
    ],
)
def test_evaluates_supported_forms(scope, source, expected):
    assert evaluate(source, scope) == expected


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('id')",
        "(1).__class__.__bases__",
        "input.__dict__",
        "[x for x in input.tags]",
        "open('/etc/passwd')",
        "lambda: 1",
        "10 ** 10 ** 10",
    ],
)
def test_rejects_escapes(scope, source):
    with pytest.raises(ExpressionError):
        evaluate(source, scope)


def test_unknown_name_is_an_error(scope):
    with pytest.raises(ExpressionError, match="unknown name"):
        evaluate("nope", scope)


def test_render_inlines_values_and_json(scope):
    out = render("cat={{ category }} tags={{ input.tags }}", scope)
    assert "cat=Bug" in out
    assert '"p1"' in out


def test_compile_reports_syntax_errors_early():
    with pytest.raises(ExpressionError, match="syntax error"):
        compile_expr("a ==")


def test_a_missing_key_names_itself_and_what_was_there():
    with pytest.raises(ExpressionError) as exc:
        render("{{ input.journal }}", {"input": wrap({"message": "hi", "count": 2})})
    assert "journal" in str(exc.value)
    assert "count, message" in str(exc.value)


# -- the words a YAML author already types ----------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("true", True),
        ("false", False),
        ("null", None),
        ("true and not false", True),
        ("category if true else 'no'", "Bug"),
        ("review.approved == false", True),
    ],
)
def test_yaml_spells_its_literals_in_lower_case(source, expected, scope):
    """Every expression poieo evaluates was typed into a YAML file.

    Python's `True` still works and is what the source is parsed as; these are
    aliases, so an author who writes what the file format taught them gets what
    they meant rather than `unknown name 'true'` at 3am. That mistake is
    especially quiet in a task's `then:` block, where an unreadable condition
    is logged and skipped rather than raised.
    """
    assert evaluate(source, scope) is expected


def test_a_scope_of_its_own_outranks_the_literals(scope):
    """Aliases must not shadow real data: the scope is checked first."""
    assert evaluate("true", wrap({"true": "mine"})) == "mine"


def test_python_spelling_still_works(scope):
    assert evaluate("True and not False", scope) is True
    assert evaluate("None == None", scope) is True
