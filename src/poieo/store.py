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

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        self._ensure()
        line = json.dumps(unwrap(record), ensure_ascii=False, default=str)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def append(self, event: Event) -> None:
        self._append(self.runs_dir / f"{event.run_id}.jsonl", event.as_dict())

    def record_summary(self, summary: dict[str, Any]) -> None:
        self._append(self.index_path, summary)

    # -- reads ---------------------------------------------------------------
    def list_runs(self, limit: int = 20, flow: str | None = None) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.index_path.open(encoding="utf-8") as handle:
            for line in handle:
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
        return rows[-limit:][::-1]

    def run(self, run_id: str) -> dict[str, Any] | None:
        """The index row for one run, or None if the store never saw it.

        Scans the index rather than holding it: the log is append-only and a
        long-lived daemon's is large, so building the whole list to find one
        row costs memory nobody needed.
        """
        if not self.index_path.exists():
            return None
        found: dict[str, Any] | None = None
        with self.index_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or run_id not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("run_id") == run_id:
                    found = row  # keep the newest; a run may be re-recorded
        return found

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
