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
from typing import Any, Iterator

from .expr import unwrap


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _lines_backwards(path: Path, block: int = 65536) -> Iterator[str]:
    """Lines of a file, last line first, reading only as far as consumed.

    The index is append-only and answers are almost always near the end, so
    readers walk fixed-size blocks from EOF instead of loading a month of
    history. Splitting on newlines happens on bytes; a line is only decoded
    once it is whole, so multi-byte text spanning a block boundary is safe.
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
    """Writes events under ``root/runs``. Safe for concurrent flows in one process."""

    def __init__(self, root: str | Path = ".poieo"):
        self.root = Path(root)
        self.runs_dir = self.root / "runs"
        self.index_path = self.runs_dir / "index.jsonl"
        self._lock = threading.Lock()
        self._ensured = False

    def _ensure(self) -> None:
        if not self._ensured:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            self._ensured = True

    def _append(self, path: Path, record: dict[str, Any], sync: bool = False) -> None:
        """Append one line; fsync only when asked.

        Events arrive one per model turn and per tool call, from coroutines on
        the loop the daemon shares with the web server, and an fsync is
        milliseconds of everything standing still. So events settle for the OS
        cache (close flushes them), and durability is bought once per run: the
        index line is synced, and it is the index that answers "what ran".
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
        self._append(self.runs_dir / f"{event.run_id}.jsonl", event.as_dict())

    def record_summary(self, summary: dict[str, Any]) -> None:
        self._append(self.index_path, summary, sync=True)

    # -- reads ---------------------------------------------------------------
    def list_runs(self, limit: int = 20, flow: str | None = None) -> list[dict[str, Any]]:
        """The newest ``limit`` summaries, newest first.

        Read from the end and parsed only until enough have matched. The index
        grows for the daemon's lifetime and the web UI asks per request, so
        parsing all of history to show the last twenty would make a month of
        uptime cost half a second per call -- measured, not feared.
        """
        if not self.index_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in _lines_backwards(self.index_path):
            if len(rows) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if flow and row.get("flow") != flow:
                continue
            rows.append(row)
        return rows

    def run(self, run_id: str) -> dict[str, Any] | None:
        """The index row for one run, or None if the store never saw it.

        Walks the index backwards and stops at the first hit: a run may be
        re-recorded, and reading from the end makes the newest record the
        first one found -- without scanning a long-lived daemon's whole log
        for every diff view and accept click.
        """
        if not self.index_path.exists():
            return None
        for line in _lines_backwards(self.index_path):
            line = line.strip()
            if not line or run_id not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("run_id") == run_id:
                return row  # newest first; a run may be re-recorded
        return None

    def events(self, run_id: str) -> Iterator[dict[str, Any]]:
        path = self.runs_dir / f"{run_id}.jsonl"
        if not path.exists():
            return iter(())

        def _iter() -> Iterator[dict[str, Any]]:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue

        return _iter()


class NullStore(RunStore):
    """Drops everything -- used by ``poieo run --no-log`` and by tests."""

    def __init__(self) -> None:
        super().__init__(".poieo")

    def append(self, event: Event) -> None:  # noqa: D102
        return

    def record_summary(self, summary: dict[str, Any]) -> None:  # noqa: D102
        return
