"""The project's memory: what it always requires, and what it has learned.

``entries``   where it is kept, and the shape of what is in it
``index``     a derived lookup over the pieces, safe to rebuild at any time
``recall``    choosing which entries a task is shown, and building the block
``results``   the full record every run leaves behind
``upkeep``    what the memory would like a person to look at

One SQLite database per project, at ``memory/longterm.sqlite3``, and its
existence is the whole opt-in. It is not a cache -- it is the memory, and
nothing holds a second copy. Every write goes through one door and leaves a
line of history behind it.

``recall.recall`` is deliberately not re-exported: reaching for it from outside
this package means reaching past ``read_memory``, which is the answer
everything else wants.

Design: docs/memory.md
"""

from .entries import (
    Entry,
    check_memory,
    entry_named,
    frontmatter,
    history_of,
    keeps_memory,
    open_memory,
    page_written_at,
    read_page,
    readable_entries,
    set_aside,
    start_memory,
    write_entry,
    write_page,
)
from .judgements import candidates as judge_candidates
from .judgements import is_stale as judgement_is_stale
from .judgements import remember as remember_judgement
from .recall import read_memory
from .results import results_dir, used_in, write_result
from .upkeep import doubts, memory_report, overview_watch_paths

__all__ = [
    "Entry",
    "check_memory",
    "doubts",
    "entry_named",
    "frontmatter",
    "history_of",
    "judge_candidates",
    "judgement_is_stale",
    "keeps_memory",
    "memory_report",
    "overview_watch_paths",
    "open_memory",
    "page_written_at",
    "read_memory",
    "read_page",
    "readable_entries",
    "remember_judgement",
    "results_dir",
    "set_aside",
    "start_memory",
    "used_in",
    "write_entry",
    "write_page",
    "write_result",
]
