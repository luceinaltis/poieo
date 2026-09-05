from conftest import EXAMPLES

from poieo.binding import load_binding
from poieo.graph import GraphSpec, load_graph
from poieo.viewer import _node_card, mermaid_source, render_page


def test_each_terminal_branch_gets_its_own_end_node():
    graph = load_graph(EXAMPLES / "tasks/draft-review.graph.yaml")
    source = mermaid_source(graph)

    # Two different exit conditions must not collapse into one drawn node.
    ends = {line.split("(")[0].strip() for line in source.splitlines() if '(["end"])' in line}
    assert len(ends) == 2
    assert 'gate -->|"approved"|' in source
    assert source.count('(["end"])') == 2


def test_cycle_edges_are_drawn():
    source = mermaid_source(load_graph(EXAMPLES / "tasks/draft-review.graph.yaml"))
    assert "revise --> review" in source
    assert "class draft entry" in source


def test_router_without_a_default_still_gets_a_fallback_edge():
    graph = GraphSpec.model_validate(
        {
            "name": "r",
            "entry": "a",
            "nodes": [
                {"id": "a", "type": "router", "branches": [{"when": "True", "to": "b"}]},
                {"id": "b", "type": "agent", "prompt": "hi"},
            ],
        }
    )
    source = mermaid_source(graph)
    assert 'a -->|"default"| a__end_default' in source


def test_page_embeds_prompts_and_binding_targets():
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    binding = load_binding(EXAMPLES / "models/hybrid.yaml")
    page = render_page([graph], binding)

    assert "<!doctype html>" in page
    assert "<title>support-triage</title>" in page
    assert "llama3.2:3b" in page  # the classifier's physical model
    assert "claude-opus-5" in page  # the writer's
    assert "Classify the support message" in page


def test_prompt_text_is_escaped():
    graph = GraphSpec.model_validate(
        {
            "name": "x",
            "entry": "a",
            "nodes": [{"id": "a", "type": "agent", "prompt": "<script>alert(1)</script>"}],
        }
    )
    page = render_page([graph])
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_fragment_mode_omits_the_document_shell_and_cdn():
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    page = render_page([graph], embed_mermaid_script=False, full_document=False)
    assert "<!doctype html>" not in page
    assert "cdn.jsdelivr.net" not in page
    assert '<pre class="mermaid">' in page


def test_multiple_graphs_render_in_one_page():
    graphs = [
        load_graph(EXAMPLES / "tasks/support-triage.graph.yaml"),
        load_graph(EXAMPLES / "tasks/draft-review.graph.yaml"),
    ]
    page = render_page(graphs)
    assert page.count('<section class="graph">') == 2
    assert "<title>2 graphs</title>" in page
    assert page.count("<h2>Graph</h2>") == 2
    assert "<h2>Flow</h2>" not in page


def _card(graph: GraphSpec, node_id: str) -> str:
    node = next(node for node in graph.nodes if node.id == node_id)
    return _node_card(node, graph, None)


def test_command_card_shows_the_command_and_its_successor():
    graph = GraphSpec.model_validate(
        {
            "name": "c",
            "entry": "build",
            "nodes": [
                {
                    "id": "build",
                    "type": "command",
                    "command": "make test",
                    "timeout": 30,
                    "next": "report",
                },
                {"id": "report", "type": "agent", "prompt": "say how it went"},
            ],
        }
    )
    card = _card(graph, "build")

    assert "make test" in card
    assert "<code>report</code>" in card
    # A command node does not branch, so it has no fallback arm to draw.
    assert "default" not in card
    assert "timeout" in card


def test_command_card_shows_a_script_with_its_language():
    graph = GraphSpec.model_validate(
        {
            "name": "c",
            "entry": "count",
            "nodes": [
                {
                    "id": "count",
                    "type": "command",
                    "script": "print(1)",
                    "language": "python",
                }
            ],
        }
    )
    card = _card(graph, "count")

    assert "print(1)" in card
    assert "python" in card
    assert "script" in card
    assert "default" not in card
    # Nothing follows it, so the run ends here.
    assert "<code>end</code>" in card


def test_confirm_card_shows_the_question_and_its_choices():
    graph = GraphSpec.model_validate(
        {
            "name": "c",
            "entry": "ask",
            "nodes": [
                {
                    "id": "ask",
                    "type": "confirm",
                    "prompt": "Ship it?",
                    "choices": ["ship", "hold"],
                }
            ],
        }
    )
    card = _card(graph, "ask")

    assert "Ship it?" in card
    assert "ship" in card
    assert "hold" in card
    # It names no successor: the card's `then:` reads the answer.
    assert "default" not in card
    assert "next &rarr;" not in card
