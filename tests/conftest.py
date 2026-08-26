import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXAMPLES = ROOT / "examples"

from poieo.layout import Layout  # noqa: E402  (needs the path above)


def at(root) -> Layout:
    """Where a project keeps things, for a root the test already knows.

    Tests used to spell `tmp_path / "tasks" / "memory" / "facts"` by hand, in
    six files. Asking the same object the code asks means the next time the
    layout moves, the tests follow from one place -- and a test that quietly
    checked the wrong folder would have been the worst kind of green.
    """
    return Layout(root=Path(root))
