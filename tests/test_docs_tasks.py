"""The node keys `docs/tasks.md` names, held against the ones the loader uses.

`_NODE_KEYS` is the list a card with a `graph:` of its own may not also set, and
`docs/tasks.md` writes it out in prose. The two drifted: `deadline` was added to
the code and never to the sentence, so a card the document called legal failed
validation with no way to find out why except reading `card.py`.

A reader cannot check this one by eye -- both lists are correct-looking on their
own -- which is what puts it here rather than under merge condition 5.

Design: docs/tasks.md
"""

from __future__ import annotations

import re
from pathlib import Path

from poieo.card import _NODE_KEYS

TASKS = Path(__file__).resolve().parents[1] / "docs" / "tasks.md"

# The run of backticked keys leading into the claim they make about themselves.
# Whitespace-tolerant throughout: the sentence is wrapped for a reader, and where
# the line breaks falls in it is not something this test should have an opinion on.
CLAUSE = re.compile(r"((?:`[^`]+`[,\s]+(?:and\s+)?)+)describe\s+the\s+generated\s+node")


def test_the_document_names_every_node_key():
    """Order is the sentence's own -- it reads for a person, not for a tuple."""
    clause = CLAUSE.search(TASKS.read_text(encoding="utf-8"))
    assert clause, "docs/tasks.md no longer lists the keys that describe the generated node"

    named = set(re.findall(r"`([^`]+)`", clause.group(1)))
    assert named == set(_NODE_KEYS), f"docs/tasks.md names {sorted(named)}, card.py {sorted(_NODE_KEYS)}"
