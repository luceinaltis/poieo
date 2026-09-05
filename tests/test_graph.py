import pytest
from conftest import EXAMPLES
from pydantic import ValidationError

from poieo.errors import SpecError
from poieo.graph import GraphSpec, load_graph


def test_loads_example_graphs():
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    assert graph.entry == "classify"
    assert graph.roles() == {"classifier", "writer"}
    assert graph.node("route").type == "router"


def test_cycles_are_allowed():
    graph = load_graph(EXAMPLES / "tasks/draft-review.graph.yaml")
    assert graph.node("revise").next == "review"


def _spec(**overrides):
    base = {
        "name": "t",
        "entry": "a",
        "nodes": [{"id": "a", "type": "agent", "prompt": "hi"}],
    }
    base.update(overrides)
    return base


def test_rejects_dangling_edge():
    with pytest.raises(Exception, match="unknown node 'ghost'"):
        GraphSpec.model_validate(_spec(nodes=[{"id": "a", "type": "agent", "prompt": "hi", "next": "ghost"}]))


def test_rejects_unknown_entry():
    with pytest.raises(Exception, match="entry node 'zzz' is not defined"):
        GraphSpec.model_validate(_spec(entry="zzz"))


def test_rejects_unreachable_node():
    with pytest.raises(Exception, match="unreachable nodes"):
        GraphSpec.model_validate(
            _spec(
                nodes=[
                    {"id": "a", "type": "agent", "prompt": "hi"},
                    {"id": "orphan", "type": "agent", "prompt": "hi"},
                ]
            )
        )


def test_rejects_duplicate_ids():
    with pytest.raises(Exception, match="duplicate node ids"):
        GraphSpec.model_validate(
            _spec(
                nodes=[
                    {"id": "a", "type": "agent", "prompt": "hi"},
                    {"id": "a", "type": "agent", "prompt": "hi"},
                ]
            )
        )


def test_rejects_bad_template_at_load_time():
    with pytest.raises(Exception, match="syntax error"):
        GraphSpec.model_validate(_spec(nodes=[{"id": "a", "type": "agent", "prompt": "{{ 1 + }}"}]))


def test_router_must_have_branches():
    with pytest.raises(Exception, match="requires at least one branch"):
        GraphSpec.model_validate(_spec(nodes=[{"id": "a", "type": "router"}]))


def test_missing_file_is_a_spec_error(tmp_path):
    with pytest.raises(SpecError, match="file not found"):
        load_graph(tmp_path / "nope.yaml")


def test_a_typo_in_a_node_is_explained_and_a_near_miss_suggested(tmp_path):
    """A graph file's typo has to read like a task file's typo.

    Every other spec loader runs its failure through describe_invalid; the
    graph loader used to hand the reader pydantic's own rendering, which is
    the exact thing describe_invalid exists to stop.
    """
    path = tmp_path / "g.yaml"
    path.write_text("name: g\nentry: a\nnodes: [{id: a, type: agent, promt: hi}]\n", encoding="utf-8")

    with pytest.raises(SpecError) as caught:
        load_graph(path)

    message = str(caught.value)
    assert "'nodes.0.promt' is not a setting here" in message
    # The suggestion has to survive the nesting: a node's settings are as
    # much a part of a graph file as the graph's own.
    assert "did you mean 'prompt'?" in message
    assert "errors.pydantic.dev" not in message


def test_a_missing_graph_key_is_named_plainly(tmp_path):
    path = tmp_path / "g.yaml"
    path.write_text("entry: a\nnodes: [{id: a, type: agent, prompt: hi}]\n", encoding="utf-8")

    with pytest.raises(SpecError, match="'name' is required"):
        load_graph(path)


def _agent_graph(**overrides):
    node = {
        "id": "work",
        "type": "agent",
        "role": "worker",
        "workdir": "/tmp/proj",
        "prompt": "do the thing",
    }
    node.update(overrides)
    return {"name": "g", "entry": "work", "nodes": [node]}


def test_agent_node_parses_with_defaults():
    graph = GraphSpec.model_validate(_agent_graph())
    node = graph.node("work")
    assert node.max_turns == 20
    assert node.tools is None  # None means every toolset


def test_agent_node_may_leave_workdir_to_the_flow():
    # Where the work happens is physical, and the graph is the logical layer.
    # A missing workdir is now preflight's business, not the schema's.
    graph = GraphSpec.model_validate(_agent_graph(workdir=None))
    assert graph.node("work").workdir is None


def test_agent_node_rejects_unknown_toolset():
    with pytest.raises(ValidationError, match="parachute"):
        GraphSpec.model_validate(_agent_graph(tools=["parachute"]))


def test_agent_node_rejects_branches():
    with pytest.raises(ValidationError, match="branches"):
        GraphSpec.model_validate(_agent_graph(branches=[{"when": "True", "to": None}]))


def test_a_router_takes_no_workdir_or_tools():
    """It calls no model and runs no tool, so it has nowhere to put either.

    This is what is left of the rule that used to refuse a workdir on an `llm`
    node: with one model node there is no such thing to refuse, and a router
    is the only node that still cannot want one.
    """
    spec = {
        "name": "g",
        "entry": "a",
        "nodes": [
            {
                "id": "a",
                "type": "router",
                "branches": [{"when": "true", "to": None}],
                "workdir": "/x",
            }
        ],
    }
    with pytest.raises(ValidationError, match="workdir"):
        GraphSpec.model_validate(spec)


def test_a_model_node_may_have_no_tools_and_no_workdir():
    """What `type: llm` used to be, said with the tools line instead."""
    graph = GraphSpec.model_validate(
        {"name": "g", "entry": "a", "nodes": [{"id": "a", "type": "agent", "prompt": "p"}]}
    )

    assert graph.node("a").tools is None


def test_roles_includes_agent_nodes():
    graph = GraphSpec.model_validate(_agent_graph())
    assert graph.roles() == {"worker"}


def test_a_graph_that_still_says_llm_is_told_what_to_do():
    """`Literal` would answer "Input should be 'agent' or 'router'" -- true, and
    no help at all to someone holding a graph that worked last week."""
    spec = {"name": "g", "entry": "a", "nodes": [{"id": "a", "type": "llm", "prompt": "p"}]}

    with pytest.raises(ValidationError, match="now 'agent' with no tools"):
        GraphSpec.model_validate(spec)


# -- the command node: a step that calls no model ----------------------------


def _graph(node: dict) -> dict:
    return {"name": "g", "entry": "n", "nodes": [{"id": "n", **node}]}


def test_a_command_node_needs_a_command():
    with pytest.raises(ValidationError, match="requires a command"):
        GraphSpec.model_validate(_graph({"type": "command"}))


def test_a_command_node_refuses_the_model_keys():
    """`role`, `system`, `prompt`, `params`, `retry`, `max_turns` and `tools`
    are all about calling a model, and this node calls none. A key that does
    nothing is worse than one that is missing: it reads as configured."""
    for key, value in [
        ("role", "writer"),
        ("system", "be terse"),
        ("prompt", "hello"),
        ("params", {"temperature": 0}),
        ("tools", ["shell"]),
        ("max_turns", 3),
    ]:
        with pytest.raises(ValidationError, match="does not take"):
            GraphSpec.model_validate(_graph({"type": "command", "command": "true", key: value}))


def test_a_command_node_takes_what_it_needs():
    graph = GraphSpec.model_validate(
        _graph(
            {
                "type": "command",
                "command": "pytest -q",
                "workdir": "~/src/thing",
                "timeout": 30,
                "env": {"CI": "1"},
                "output": {"as": "check"},
            }
        )
    )
    node = graph.node("n")
    assert node.command == "pytest -q"
    assert node.timeout == 30
    assert node.env == {"CI": "1"}


def test_a_command_node_needs_no_role():
    """It calls no model, so it must not make the binding answer for one."""
    graph = GraphSpec.model_validate(_graph({"type": "command", "command": "true"}))
    assert graph.roles() == set()


def test_an_agent_node_may_not_carry_a_command():
    with pytest.raises(ValidationError, match="command"):
        GraphSpec.model_validate(_graph({"type": "agent", "prompt": "hi", "command": "pytest"}))


def test_a_commands_workdir_is_a_template_like_an_agents():
    with pytest.raises(ValidationError):
        GraphSpec.model_validate(_graph({"type": "command", "command": "true", "workdir": "{{ 1 + }}"}))


def test_a_bad_template_in_a_command_fails_at_load_not_at_3am():
    """`prompt` and `workdir` are checked when the graph parses. A command is
    rendered the same way and was not, so a typo in one waited until the
    trigger fired -- which is the failure principle 5 exists to refuse."""
    with pytest.raises(ValidationError):
        GraphSpec.model_validate(_graph({"type": "command", "command": "pytest {{ 1 + }}"}))


def test_a_good_template_in_a_command_is_allowed():
    graph = GraphSpec.model_validate(_graph({"type": "command", "command": "pytest {{ input.suite }}"}))
    assert "{{ input.suite }}" in graph.node("n").command


def test_a_multi_line_command_is_refused_at_load():
    """Two lines in a `command:` run as one shell string, and Windows `cmd`
    drops everything after the first newline while still reporting exit 0 --
    a step that did half its work and called it success. Verified by hand;
    refused here rather than at 3am."""
    with pytest.raises(ValidationError) as caught:
        GraphSpec.model_validate(_graph({"type": "command", "command": "echo one\necho two"}))

    said = str(caught.value)
    # The refusal names the three better routes, since all of them are.
    assert "&&" in said and "script" in said


def test_a_trailing_newline_is_not_a_second_line():
    """`command: |` adds one, and YAML block scalars are the readable way to
    write a long command. Refusing that would be refusing the good spelling."""
    graph = GraphSpec.model_validate(_graph({"type": "command", "command": "pytest -q\n"}))
    assert graph.node("n").command == "pytest -q"


# -- script: the node carries its own code -----------------------------------


def test_a_script_needs_a_language():
    """Nothing can be inferred from the text, and guessing wrong runs the
    wrong interpreter over somebody's code."""
    with pytest.raises(ValidationError, match="language"):
        GraphSpec.model_validate(_graph({"type": "command", "script": "print(1)"}))


def test_a_language_needs_a_script():
    with pytest.raises(ValidationError, match="script"):
        GraphSpec.model_validate(_graph({"type": "command", "language": "python"}))


def test_a_command_and_a_script_are_exclusive():
    with pytest.raises(ValidationError, match="command"):
        GraphSpec.model_validate(
            _graph(
                {
                    "type": "command",
                    "command": "pytest",
                    "language": "python",
                    "script": "print(1)",
                }
            )
        )


def test_an_unknown_language_is_refused_by_name():
    with pytest.raises(ValidationError, match="cobol"):
        GraphSpec.model_validate(_graph({"type": "command", "language": "cobol", "script": "x"}))


def test_a_script_keeps_its_newlines():
    """The whole point: code, not a shell string. A block scalar is the
    ordinary way to write it and nothing here may flatten it."""
    code = "import json\nprint(json.dumps({'k': 1}))\n"
    graph = GraphSpec.model_validate(_graph({"type": "command", "language": "python", "script": code}))
    assert graph.node("n").script == code


def test_a_bad_template_in_a_script_fails_at_load():
    with pytest.raises(ValidationError):
        GraphSpec.model_validate(_graph({"type": "command", "language": "python", "script": "x = {{ 1 + }}"}))


def test_a_scripted_node_still_calls_no_model():
    graph = GraphSpec.model_validate(_graph({"type": "command", "language": "python", "script": "print(1)"}))
    assert graph.roles() == set()


# -- compiled languages ------------------------------------------------------


def test_a_compiled_script_is_refused_a_template():
    """A compiled script is cached by its own text, so a template in it would
    never be substituted. What varies belongs in `env`, which is templated and
    does not reach the compiler."""
    with pytest.raises(ValidationError) as caught:
        GraphSpec.model_validate(
            _graph(
                {
                    "type": "command",
                    "language": "c",
                    "script": "int main(void){return {{ input.code }};}",
                }
            )
        )

    assert "env" in str(caught.value)


@pytest.mark.parametrize(
    "language,script",
    [
        ("go", "grid := [][]int{{1, 2}, {3, 4}}"),
        ("c", "int m[2][2] = {{1, 0}, {0, 1}};"),
        ("c", "int m[1][1] = {{0}};"),
        ("rust", "let m = [[1, 2], [3, 4]];"),
    ],
)
def test_braces_a_language_owns_are_not_a_template(language, script):
    """`{{` is a template only where the text *is* one. A nested initializer is
    ordinary C and ordinary Go, and refusing it would be refusing the
    language."""
    graph = GraphSpec.model_validate(_graph({"type": "command", "language": language, "script": script}))

    assert graph.node("n").script == script


def test_a_bad_template_in_env_fails_at_load():
    """`env` is rendered, so it is checked where every other template is."""
    with pytest.raises(ValidationError) as caught:
        GraphSpec.model_validate(
            _graph(
                {
                    "type": "command",
                    "command": "true",
                    "env": {"FLOOR": "{{ input.floor( }}"},
                }
            )
        )

    assert "FLOOR" in str(caught.value)


def test_an_interpreted_script_still_takes_a_template():
    """Nothing is compiled, so nothing is cached, so nothing is defeated."""
    graph = GraphSpec.model_validate(
        _graph(
            {
                "type": "command",
                "language": "python",
                "script": "print('{{ input.who }}')",
            }
        )
    )
    assert "{{ input.who }}" in graph.node("n").script


def test_a_compiled_script_without_a_template_is_fine():
    graph = GraphSpec.model_validate(
        _graph({"type": "command", "language": "c", "script": "int main(void){return 0;}"})
    )
    assert graph.node("n").language == "c"


@pytest.mark.parametrize("language", ["c", "go", "rust"])
def test_every_compiled_language_is_accepted(language):
    GraphSpec.model_validate(_graph({"type": "command", "language": language, "script": "x"}))


def test_a_confirm_node_asks_a_person_and_offers_choices():
    graph = GraphSpec.model_validate(_graph({"type": "confirm", "prompt": "Merge it?", "choices": ["merge", "hold"]}))
    assert graph.node("n").choices == ["merge", "hold"]


def test_a_confirm_node_needs_something_to_ask():
    with pytest.raises(ValidationError, match="has nothing to ask"):
        GraphSpec.model_validate(_graph({"type": "confirm", "choices": ["a", "b"]}))


def test_a_confirm_node_needs_at_least_two_choices():
    """One choice is not a decision, and no choices is free text -- which is
    the `'HOLD' in text` reading this node exists to stop."""
    with pytest.raises(ValidationError, match="two choices"):
        GraphSpec.model_validate(_graph({"type": "confirm", "prompt": "Merge it?", "choices": ["merge"]}))


def test_a_confirm_nodes_choices_must_differ():
    with pytest.raises(ValidationError, match="twice"):
        GraphSpec.model_validate(_graph({"type": "confirm", "prompt": "?", "choices": ["yes", "yes"]}))


def test_a_confirm_node_refuses_a_next():
    """The run ends at the question. What happens after the answer is the
    card's `then:`, one level up, because the answer arrives after the run."""
    with pytest.raises(ValidationError, match="ends the run"):
        GraphSpec.model_validate(
            {
                "name": "g",
                "entry": "n",
                "nodes": [
                    {
                        "id": "n",
                        "type": "confirm",
                        "prompt": "?",
                        "choices": ["a", "b"],
                        "next": "after",
                    },
                    {"id": "after", "type": "agent", "prompt": "go"},
                ],
            }
        )


def test_only_a_confirm_node_takes_choices():
    with pytest.raises(ValidationError, match="does not offer choices"):
        GraphSpec.model_validate(_graph({"type": "agent", "prompt": "hi", "choices": ["a", "b"]}))


def test_a_confirm_node_refuses_the_model_keys():
    """It calls no model, exactly as a command node does not -- and says so in
    the same words, because two phrasings for one rule is one too many.

    `prompt` is the exception, and the only one: a confirm node has one, and it
    is read by a person rather than sent anywhere."""
    with pytest.raises(ValidationError, match="it calls no model"):
        GraphSpec.model_validate(_graph({"type": "confirm", "prompt": "?", "choices": ["a", "b"], "role": "r"}))


def test_a_confirm_node_takes_no_workdir():
    """Nothing runs at the question: a person reads it and the run ends. A
    workdir there configures nothing, exactly as it does on a router."""
    with pytest.raises(ValidationError, match="workdir"):
        GraphSpec.model_validate(_graph({"type": "confirm", "prompt": "?", "choices": ["a", "b"], "workdir": "/tmp"}))


def test_a_confirm_node_without_a_workdir_still_loads():
    graph = GraphSpec.model_validate(_graph({"type": "confirm", "prompt": "?", "choices": ["a", "b"]}))
    assert graph.node("n").workdir is None
