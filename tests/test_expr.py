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
