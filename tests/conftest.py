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


def card(folder, name: str, body: str = "") -> Path:
    """One job, as its own file.

    A job is declared one way -- a card in the tasks folder -- so the tests
    declare them that way too. `body` is the rest of the card's YAML; the name
    and the folder it lives in are the two things every one of them needs.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.yaml"
    path.write_text(f"name: {name}\n{body}", encoding="utf-8")
    return path
