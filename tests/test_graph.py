import pytest
from pydantic import ValidationError

from conftest import EXAMPLES
from poieo.errors import SpecError
from poieo.graph import GraphSpec, load_graph


def test_loads_example_graphs():
    graph = load_graph(EXAMPLES / "graphs/support-triage.yaml")
    assert graph.entry == "classify"
    assert graph.roles() == {"classifier", "writer"}
    assert graph.node("route").type == "router"


def test_cycles_are_allowed():
    graph = load_graph(EXAMPLES / "graphs/draft-review.yaml")
    assert graph.node("revise").next == "review"


def _spec(**overrides):
    base = {
        "name": "t",
        "entry": "a",
        "nodes": [{"id": "a", "type": "llm", "prompt": "hi"}],
    }
    base.update(overrides)
    return base


def test_rejects_dangling_edge():
    with pytest.raises(Exception, match="unknown node 'ghost'"):
        GraphSpec.model_validate(
            _spec(nodes=[{"id": "a", "type": "llm", "prompt": "hi", "next": "ghost"}])
        )


def test_rejects_unknown_entry():
    with pytest.raises(Exception, match="entry node 'zzz' is not defined"):
        GraphSpec.model_validate(_spec(entry="zzz"))


def test_rejects_unreachable_node():
    with pytest.raises(Exception, match="unreachable nodes"):
        GraphSpec.model_validate(
            _spec(
                nodes=[
                    {"id": "a", "type": "llm", "prompt": "hi"},
                    {"id": "orphan", "type": "llm", "prompt": "hi"},
                ]
            )
        )


def test_rejects_duplicate_ids():
    with pytest.raises(Exception, match="duplicate node ids"):
        GraphSpec.model_validate(
            _spec(
                nodes=[
                    {"id": "a", "type": "llm", "prompt": "hi"},
                    {"id": "a", "type": "llm", "prompt": "hi"},
                ]
            )
        )


def test_rejects_bad_template_at_load_time():
    with pytest.raises(Exception, match="syntax error"):
        GraphSpec.model_validate(
            _spec(nodes=[{"id": "a", "type": "llm", "prompt": "{{ 1 + }}"}])
        )


def test_router_must_have_branches():
    with pytest.raises(Exception, match="requires at least one branch"):
        GraphSpec.model_validate(_spec(nodes=[{"id": "a", "type": "router"}]))


def test_missing_file_is_a_spec_error(tmp_path):
    with pytest.raises(SpecError, match="file not found"):
        load_graph(tmp_path / "nope.yaml")


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


def test_llm_node_rejects_agent_only_fields():
    spec = {
        "name": "g",
        "entry": "a",
        "nodes": [{"id": "a", "type": "llm", "prompt": "p", "workdir": "/x"}],
    }
    with pytest.raises(ValidationError, match="workdir"):
        GraphSpec.model_validate(spec)


def test_roles_includes_agent_nodes():
    graph = GraphSpec.model_validate(_agent_graph())
    assert graph.roles() == {"worker"}
