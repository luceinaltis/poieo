"""The project's memory: what it always requires, and what it has learned.

``entries``   the files it is made of: the page, and one entry per lesson
``index``     a derived sqlite lookup over them, safe to delete at any time
``recall``    choosing which entries a task is shown, and building the block
``results``   the full record every run leaves behind
``upkeep``    what the memory would like a person to look at

Truth lives in markdown under git; ``memory/longterm/`` existing is the whole
opt-in. Everything derived lives in ``memory/cache/`` and can be deleted.

``recall.recall`` is deliberately not re-exported: reaching for it from outside
this package means reaching past ``read_memory``, which is the answer
everything else wants.

Design: docs/memory.md
"""

from .results import results_dir, used_in, write_result
from .entries import (
    Entry,
    check_memory,
    keeps_memory,
    load_entry,
    load_entries,
    read_page,
    readable_entries,
)
from .recall import read_memory
from .upkeep import doubts, memory_report

__all__ = [
    "Entry",
    "check_memory",
    "doubts",
    "keeps_memory",
    "load_entry",
    "load_entries",
    "memory_report",
    "read_memory",
    "read_page",
    "results_dir",
    "readable_entries",
    "used_in",
    "write_result",
]
