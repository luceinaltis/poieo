import json
import re

from conftest import EXAMPLES

from poieo.binding import load_binding
from poieo.editor import _boot_payload, render_editor
from poieo.graph import GraphSpec, load_graph


def boot_of(page: str) -> dict:
    return json.loads(re.search(r"const BOOT = (\{.*?\});</script>", page, re.S).group(1))


def test_boot_payload_carries_the_whole_graph():
    graph = load_graph(EXAMPLES / "tasks/draft-review.graph.yaml")
    binding = load_binding(EXAMPLES / "models/hybrid.yaml")
    payload = _boot_payload(graph, binding, {"mode": "none"})

    ids = [n["id"] for n in payload["graph"]["nodes"]]
    assert ids == ["draft", "review", "gate", "revise"]
    gate = next(n for n in payload["graph"]["nodes"] if n["id"] == "gate")
    assert gate["branches"][0]["when"] == "review.approved"
    assert gate["branches"][0]["to"] is None      # a terminal branch stays null
    assert payload["bindings"]["writer"] == "claude/claude-opus-5"


def test_every_node_has_the_fields_the_editor_expects():
    # The editor writes into node.output / node.retry / node.branches without
    # guarding, so the payload must always supply them.
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    payload = _boot_payload(graph, None, {"mode": "none"})
    for node in payload["graph"]["nodes"]:
        assert "branches" in node and "output" in node and "retry" in node


def test_unbound_roles_are_reported_not_raised():
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    binding = load_binding(EXAMPLES / "models/mock.yaml")
    binding.default.model = None                  # break the fallback
    payload = _boot_payload(graph, binding, {"mode": "none"})
    assert set(payload["bindings"].values()) == {"unbound"}


def test_ui_coordinates_round_trip_through_the_schema():
    graph = GraphSpec.model_validate(
        {
            "name": "u",
            "entry": "a",
            "nodes": [{"id": "a", "type": "agent", "prompt": "hi", "ui": {"x": 40, "y": 90}}],
        }
    )
    payload = _boot_payload(graph, None, {"mode": "none"})
    assert payload["graph"]["nodes"][0]["ui"] == {"x": 40.0, "y": 90.0}


def test_page_is_a_complete_document_with_the_save_config():
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    save = {"mode": "jupyter", "url": "/api/contents/g.yaml", "token": "t", "path": "g.yaml"}
    page = render_editor(graph, None, save=save)

    assert page.startswith("<!doctype html>")
    assert boot_of(page)["save"]["url"] == "/api/contents/g.yaml"
    assert "canvas" in page and "inspector" in page


def test_a_prompt_cannot_close_the_script_tag():
    graph = GraphSpec.model_validate(
        {
            "name": "x",
            "entry": "a",
            "nodes": [{"id": "a", "type": "agent", "prompt": 'say "</script><img>" now'}],
        }
    )
    page = render_editor(graph)
    boot_line = next(l for l in page.splitlines() if l.startswith("<script>const BOOT"))

    # The literal sequence must not appear inside the payload; the browser would
    # end the script there and render the rest of the graph as markup.
    assert "</script>" not in boot_line[: boot_line.rindex("</script>")]
    assert "<\\/script>" in boot_line
    # And it still decodes back to the original text in the browser.
    assert json.loads(boot_line[len("<script>const BOOT = "):-len(";</script>")]
                      .replace("<\\/", "</"))["graph"]["nodes"][0]["prompt"] == 'say "</script><img>" now'
