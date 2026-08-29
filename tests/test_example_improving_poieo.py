"""The shipped self-improvement example, checked for the mistakes it invites.

Every card here hands its work to the next one, and a handoff carries only the
*immediate* sender's outputs, keyed by node id. So a prompt saying
``sender.outputs.look`` is a promise about another file's node names -- and
renaming a node quietly breaks it, with no error anywhere. The receiving model
is handed the fallback string instead and judges *that*, which reads as the
model being difficult rather than as a wiring fault.

Twice while building this example a node was renamed and a consumer was not.
Both times the chain ran to completion and produced nothing. This is the check
that would have said so.
"""

import re

from conftest import EXAMPLES

from poieo.card import load_card
from poieo.graph import load_graph

PROJECT = EXAMPLES / "improving-poieo"
SENDER_OUTPUT = re.compile(
    r"sender['\"]?[^)]*\)\s*\.get\(\s*['\"]outputs['\"][^)]*\)\s*"
    r"\.get\(\s*['\"](?P<key>\w+)['\"]"
)


def _cards() -> dict:
    return {
        card.name: card
        for path in sorted(PROJECT.glob("tasks/*.yaml"))
        if not path.name.endswith(".graph.yaml")
        for card in [load_card(path)]
    }


def _graph_of(card):
    return load_graph(PROJECT / "tasks" / card.graph)


def _keys_read(graph) -> set[str]:
    """Node ids this graph expects to find in whatever hands it work."""
    text = "\n".join((node.prompt or "") + "\n" + (node.system or "") for node in graph.nodes)
    return {m.group("key") for m in SENDER_OUTPUT.finditer(text)}


def test_every_handoff_reads_a_node_its_sender_actually_has():
    cards = _cards()
    graphs = {name: _graph_of(card) for name, card in cards.items()}

    checked = 0
    for name, card in cards.items():
        for branch in card.then:
            if branch.to is None:
                continue
            assert branch.to in cards, f"'{name}' hands to '{branch.to}', which is not a card"
            wanted = _keys_read(graphs[branch.to])
            have = {node.id for node in graphs[name].nodes}
            missing = wanted - have
            assert not missing, (
                f"'{branch.to}' reads sender.outputs{sorted(missing)}, but its sender "
                f"'{name}' has no such node -- it has {sorted(have)}. The receiving "
                f"model gets the fallback string and judges that instead."
            )
            checked += 1

    # A green run over nothing would be worse than no test at all.
    assert checked >= 3, f"only {checked} handoffs checked; the example has more"
