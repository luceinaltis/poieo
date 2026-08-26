"""The project's memory: what it always requires, and what it has learned.

A task's journal is short-term on purpose -- old lines age out of the
prompt. This package is the long-term half, in five parts:

``facts``     the files it is made of: the page, and one entry per lesson
``index``     a derived sqlite lookup over them, safe to delete at any time
``recall``    choosing which entries a task is shown, and building the block
``results``   the full record every run leaves behind
``upkeep``    what the memory would like a person to look at

Truth lives in markdown under git -- the journals in ``memory/shortterm/``
and the rest in ``memory/longterm/``, whose existence is the whole opt-in.
Everything a machine derives lives in ``memory/cache/`` and can be deleted
without loss.

What is re-exported here is what the rest of poieo asks for. The ranking
itself is deliberately not: ``recall.recall`` would shadow the module of the
same name, and reaching for it from outside this package means reaching past
``read_memory``, which is the answer everything else wants.

Design: docs/memory.md
"""

from .results import results_dir, used_in, write_result
from .facts import (
    Fact,
    check_memory,
    keeps_memory,
    load_fact,
    load_facts,
    read_page,
    readable_facts,
)
from .recall import read_memory
from .upkeep import doubts, memory_report

__all__ = [
    "Fact",
    "check_memory",
    "doubts",
    "keeps_memory",
    "load_fact",
    "load_facts",
    "memory_report",
    "read_memory",
    "read_page",
    "results_dir",
    "readable_facts",
    "used_in",
    "write_result",
]
