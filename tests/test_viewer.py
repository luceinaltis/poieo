from conftest import EXAMPLES

from poieo.binding import load_binding
from poieo.graph import GraphSpec, load_graph
from poieo.viewer import mermaid_source, render_page


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


def test_a_confirm_card_shows_the_question_and_every_choice():
    """A confirm node asks a person something and offers a fixed set of
    answers. Drawn as a branch list it said neither: the question was dropped
    and the only row was a `default` the node does not have."""
    graph = GraphSpec.model_validate(
        {
            "name": "c",
            "entry": "a",
            "nodes": [
                {"id": "a", "type": "agent", "prompt": "draft it", "next": "gate"},
                {
                    "id": "gate",
                    "type": "confirm",
                    "prompt": "Ship the release?",
                    "choices": ["ship", "hold"],
                },
            ],
        }
    )
    page = render_page([graph])

    assert "Ship the release?" in page
    assert '<code class="choice">ship</code><span class="hop">&rarr;</span><code>end</code>' in page
    assert '<code class="choice">hold</code><span class="hop">&rarr;</span><code>end</code>' in page
    # The run ends at the question, so there is no default arm to name.
    assert 'class="fallback">default' not in page
