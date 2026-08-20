"""Entry point: `python main.py ...` is the same as the `poieo` command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from poieo.cli import app  # noqa: E402

if __name__ == "__main__":
    app()
