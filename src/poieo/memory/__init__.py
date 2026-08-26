"""The project's memory: what it always requires, and what it has learned.

A task's journal is short-term on purpose -- old lines age out of the
prompt. This package is the long-term half, in five parts:

``facts``     the files it is made of: the page, and one entry per lesson
``index``     a derived sqlite lookup over them, safe to delete at any time
``recall``    choosing which entries a task is shown, and building the block
``episodes``  the full record every run leaves behind
``upkeep``    what the memory would like a person to look at

Truth lives in markdown under git (``memory/``); everything a machine
derives lives under ``.poieo/`` and can be deleted without loss.

What is re-exported here is what the rest of poieo asks for. The ranking
itself is deliberately not: ``recall.recall`` would shadow the module of the
same name, and reaching for it from outside this package means reaching past
``read_memory``, which is the answer everything else wants.

Spec: docs/superpowers/specs/2026-08-24-project-memory-design.md
"""

from .episodes import episodes_dir, used_in, write_episode
from .facts import (
    CONSTITUTION,
    MEMORY_DIR,
    PAGE_BUDGET,
    Fact,
    check_memory,
    load_fact,
    load_facts,
    memory_root,
    read_page,
    readable_facts,
    tokens,
)
from .index import INDEX_NAME, fts_available
from .recall import FACTS_BUDGET, LEARNED_HEADER, PAGE_HEADER, read_memory
from .upkeep import ACCOUNT_WINDOW, UNUSED_FLOOR, accounting, doubts, memory_report

__all__ = [
    "ACCOUNT_WINDOW",
    "CONSTITUTION",
    "FACTS_BUDGET",
    "INDEX_NAME",
    "LEARNED_HEADER",
    "MEMORY_DIR",
    "PAGE_BUDGET",
    "PAGE_HEADER",
    "UNUSED_FLOOR",
    "Fact",
    "accounting",
    "check_memory",
    "doubts",
    "episodes_dir",
    "fts_available",
    "load_fact",
    "load_facts",
    "memory_report",
    "memory_root",
    "read_memory",
    "read_page",
    "readable_facts",
    "tokens",
    "used_in",
    "write_episode",
]
