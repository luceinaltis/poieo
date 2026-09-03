"""What `docs/graph.md` must still say about the node block.

A node key the loader accepts and no document names is a key nobody can find.
That matters most for the ones a run never reads: the editor writes them back
on save, and anything else that wants to share that save path has only the
document to agree with. Merge condition 5 is a person's job; the part of it
that is "every key has a name in the guide" is here.

Design: docs/graph.md
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from poieo.graph import NodeSpec, UiSpec

DOC = Path(__file__).resolve().parents[1] / "docs" / "graph.md"

# A key counts as documented when the guide names it as a key: in backticks, or
# as `key:` in one of its YAML examples. Bare prose does not count -- "output",
# "default" and "next" are also English words, and matching those would call
# every key documented forever.
INLINE = re.compile(r"`([a-z_]+)`")
YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.S)
YAML_KEY = re.compile(r"^\s*(?:-\s*)?([a-z_]+):", re.M)


def _documented() -> set[str]:
    text = DOC.read_text(encoding="utf-8")
    names = set(INLINE.findall(text))
    for block in YAML_BLOCK.findall(text):
        names |= set(YAML_KEY.findall(block))
    return names


@pytest.mark.parametrize("key", sorted(NodeSpec.model_fields))
def test_every_node_block_key_is_documented(key: str):
    assert key in _documented(), f"docs/graph.md never names the node key `{key}`"


@pytest.mark.parametrize("key", sorted(UiSpec.model_fields))
def test_every_ui_block_key_is_documented(key: str):
    """The coordinates round-trip through a save, so both ends need the spec."""
    assert key in _documented(), f"docs/graph.md never names the `ui` key `{key}`"
