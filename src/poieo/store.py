"""Append-only run log.

The daemon is long-lived and mostly unattended, so every run writes a JSONL
event stream plus a one-line summary in an index. That is enough to answer
"what ran, what did it decide, what did it cost" without a database.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .expr import unwrap
from .layout import layout_for


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _lines_backwards(path: Path, block: int = 65536) -> Iterator[str]:
    """Lines of a file, last line first, reading only as far as consumed.

    Splitting happens on bytes and a line is decoded only once whole, so
    multi-byte text spanning a block boundary is safe.
    """
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        tail = b""
        while position > 0:
            step = min(block, position)
            position -= step
            handle.seek(position)
            lines = (handle.read(step) + tail).split(b"\n")
            tail = lines[0]
            for raw in reversed(lines[1:]):
                yield raw.decode("utf-8", errors="replace")
        if tail:
            yield tail.decode("utf-8", errors="replace")


def json_records(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """The JSON objects among some lines, skipping anything that is not one.

    The one reading rule for every JSONL file poieo writes. They are appended
    to by a long-lived daemon and are plain files the user may open, so a
    blank line or a half-written last one is a thing that happens, and neither
    is worth refusing to answer over.
    """
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


@dataclass(slots=True)
class Event:
    run_id: str
    type: str
    at: str = field(default_factory=utcnow)
    node_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class RunStore:
    """Everything a run leaves behind, under the folder it is handed.

    That folder is the project's ``runs/``, written into straight -- no
    subfolder of its own. Safe for concurrent tasks in one process.
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else layout_for().runs()
        self.events_dir = self.root / "events"
        self.index_path = self.root / "index.jsonl"
        self._lock = threading.Lock()
        self._ensured = False

    def _ensure(self) -> None:
        if not self._ensured:
            self.events_dir.mkdir(parents=True, exist_ok=True)
            self._ensured = True

    def _append(self, path: Path, record: dict[str, Any], sync: bool = False) -> None:
        """Append one line; fsync only when asked.

        An fsync on the loop the daemon shares with the web server is
        milliseconds of everything standing still, and events arrive one per
        model turn and per tool call. So events settle for the OS cache and
        durability is bought once per run, on the index line -- which is what
        answers "what ran".
        """
        self._ensure()
        line = json.dumps(unwrap(record), ensure_ascii=False, default=str)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                if sync:
                    handle.flush()
                    os.fsync(handle.fileno())

    def append(self, event: Event) -> None:
        self._append(self.events_dir / f"{event.run_id}.jsonl", event.as_dict())

    def record_summary(self, summary: dict[str, Any]) -> None:
        self._append(self.index_path, summary, sync=True)

    # -- reads ---------------------------------------------------------------
    def _index_backwards(self, containing: str | None = None) -> Iterator[dict[str, Any]]:
        """Index rows, newest first, from an index that may not exist yet.

        ``containing`` is a cheap pre-filter on the raw line, so a lookup by
        run id skips the JSON parse for every row that cannot be the answer.
        """
        if not self.index_path.exists():
            return
        lines = _lines_backwards(self.index_path)
        if containing is not None:
            lines = (line for line in lines if containing in line)
        yield from json_records(lines)

    def list_runs(
        self,
        limit: int = 20,
        task: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """The newest ``limit`` summaries, newest first.

        Read from the end and parsed only until enough have matched: the index
        grows for the daemon's lifetime and the web UI asks per request.

        ``task`` and ``project`` narrow together, because a task name alone
        stopped being an identity once one daemon could run several projects.
        """
        rows: list[dict[str, Any]] = []
        for row in self._index_backwards():
            if len(rows) >= limit:
                break
            if task and row.get("task") != task:
                continue
            if project and row.get("project") != project:
                continue
            rows.append(row)
        return rows

    def summary(self, run_id: str) -> dict[str, Any] | None:
        """The index row for one run, or None if the store never saw it."""
        for row in self._index_backwards(containing=run_id):
            if row.get("run_id") == run_id:
                return row  # newest first; a run may be re-recorded
        return None

    def events(self, run_id: str) -> Iterator[dict[str, Any]]:
        path = self.events_dir / f"{run_id}.jsonl"
        if not path.exists():
            return iter(())

        def _iter() -> Iterator[dict[str, Any]]:
            with path.open(encoding="utf-8") as handle:
                yield from json_records(handle)

        return _iter()


class NullStore(RunStore):
    """Drops everything -- used by ``poieo run --no-log`` and by tests.

    Empty on both sides: inheriting the reads would leave it answering from
    whatever ``runs/`` a folder happens to hold.
    """

    def __init__(self) -> None:
        super().__init__("runs")

    def append(self, event: Event) -> None:  # noqa: D102
        return

    def record_summary(self, summary: dict[str, Any]) -> None:  # noqa: D102
        return

    def list_runs(self, limit: int = 20, task: str | None = None, project: str | None = None) -> list[dict[str, Any]]:  # noqa: D102
        return []

    def summary(self, run_id: str) -> dict[str, Any] | None:  # noqa: D102
        return None

    def events(self, run_id: str) -> Iterator[dict[str, Any]]:  # noqa: D102
        return iter(())
