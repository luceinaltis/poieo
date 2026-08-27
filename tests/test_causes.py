"""A failed run says why in words -- classified once, shown everywhere."""

from conftest import at
import json

from typer.testing import CliRunner

from poieo.cli import app
from poieo.errors import (
    ExpressionError,
    IsolationError,
    NodeError,
    ProviderError,
    RunAborted,
    explain_failure,
)

runner = CliRunner()


def _wrap(inner, outer_message="node 'a' failed after 2 attempt(s): gone"):
    """The real shape: a NodeError raised `from` a lower error."""
    outer = NodeError(outer_message, node_id="a")
    outer.__cause__ = inner
    return outer


# -- one test per row of the spec's table -------------------------------------


def test_an_exhausted_connection_reads_as_unreachable():
    cause = explain_failure(
        _wrap(ProviderError("local: cannot reach http://localhost:11434: refused",
                            provider="local", retryable=True))
    )
    assert cause.slug == "unreachable"
    assert "reached" in cause.said
    assert "poieo check" in cause.fix


def test_a_missing_key_reads_as_no_credentials():
    cause = explain_failure(
        _wrap(ProviderError("provider 'claude': $ANTHROPIC_API_KEY is not set"))
    )
    assert cause.slug == "no_credentials"


def test_a_4xx_reads_as_rejected():
    cause = explain_failure(
        _wrap(ProviderError("local: HTTP 404: model 'nope' not found", retryable=False))
    )
    assert cause.slug == "rejected"
    assert "binding" in cause.fix


def test_a_retryable_429_is_unreachable_not_rejected():
    # Overload is the server's mood, not the request's shape -- the fix for
    # `rejected` (edit the binding) would send the user chasing a ghost.
    cause = explain_failure(
        _wrap(ProviderError("claude: HTTP 429: overloaded", retryable=True))
    )
    assert cause.slug == "unreachable"


def test_max_turns_reads_as_out_of_turns():
    cause = explain_failure(
        NodeError("node 'work' hit max_turns (40) with tool calls still pending",
                  node_id="work")
    )
    assert cause.slug == "out_of_turns"


def test_unparseable_output_reads_as_bad_output():
    cause = explain_failure(
        NodeError("node 'a' expected JSON output but got: 'sure! here you go'")
    )
    assert cause.slug == "bad_output"


def test_a_missing_output_path_reads_as_bad_output():
    cause = explain_failure(
        NodeError("node 'a': output path 'x.y' is missing from the parsed JSON")
    )
    assert cause.slug == "bad_output"


def test_a_vanished_workdir_reads_as_folder_gone():
    cause = explain_failure(
        NodeError("node 'a': workdir does not exist: /tmp/gone")
    )
    assert cause.slug == "folder_gone"


def test_isolation_failure_reads_as_no_isolation():
    cause = explain_failure(_wrap(IsolationError("docker is not answering")))
    assert cause.slug == "no_isolation"


def test_max_steps_reads_as_cycling():
    cause = explain_failure(
        RunAborted("exceeded max_steps (50); the graph may be cycling "
                   "without an exit condition")
    )
    assert cause.slug == "cycling"


def test_a_runtime_expression_failure_reads_as_bad_expression():
    cause = explain_failure(_wrap(ExpressionError("no 'foo' here; this has: bar")))
    assert cause.slug == "bad_expression"


def test_an_unmatched_failure_carries_no_cause():
    # An honest nothing beats a wrong sentence.
    assert explain_failure(NodeError("something entirely novel")) is None


def test_a_plain_cancel_carries_no_cause():
    assert explain_failure(RunAborted("cancelled before completing the graph")) is None


# -- the cause travels with the run -------------------------------------------

_GRAPH = """\
name: wants-json
entry: a
nodes:
  - {id: a, type: agent, role: r, prompt: hi, output: {format: json}}
"""

_PROSE_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "sure! here is prose, not json"}}}
default: {provider: fake, model: m}
"""


def _write(tmp_path):
    graph = tmp_path / "g.yaml"
    graph.write_text(_GRAPH, encoding="utf-8")
    binding = tmp_path / "b.yaml"
    binding.write_text(_PROSE_MOCK, encoding="utf-8")
    return graph, binding


def test_run_prints_the_cause_and_the_fix(tmp_path):
    graph, binding = _write(tmp_path)
    result = runner.invoke(
        app, ["run", str(graph), "-b", str(binding), "--no-log"]
    )
    assert result.exit_code == 1
    assert "cause" in result.stdout
    assert "shape" in result.stdout  # the bad_output sentence
    assert "try" in result.stdout


def test_the_summary_row_carries_the_cause(tmp_path):
    graph, binding = _write(tmp_path)
    store = tmp_path / "logs"
    result = runner.invoke(
        app, ["run", str(graph), "-b", str(binding), "--store", str(store)]
    )
    assert result.exit_code == 1
    row = json.loads(
        (store / "index.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert row["cause"]["slug"] == "bad_output"


def test_a_failed_task_journals_the_sentence_not_the_repr(tmp_path):
    # One tool-calling reply against max_turns: 1 fails every time, identically.
    (tmp_path / "b.yaml").write_text(
        'name: mock\n'
        'providers:\n'
        '  fake:\n'
        '    type: mock\n'
        '    options:\n'
        '      responses:\n'
        '        "*":\n'
        '          - tool_calls: [{name: list_dir, arguments: {}}]\n'
        'default: {provider: fake, model: m}\n',
        encoding="utf-8",
    )
    card = tmp_path / "card.yaml"
    card.write_text(
        "name: doomed\nfolder: .\nmax_turns: 1\nprompt: do the thing\n"
        "binding: b.yaml\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["run", str(card), "--no-log"])
    assert result.exit_code == 1
    journal = at(tmp_path).journal("card").read_text(encoding="utf-8")
    assert "failed" in journal
    assert "ran out of turns" in journal
    assert "NodeError" not in journal
