"""Fan-out layer: every stored event is also pushed to live subscribers."""

from __future__ import annotations

import asyncio
from typing import Any, Iterator

from ..store import Event, RunStore


class BroadcastStore(RunStore):
    """Wraps a RunStore: writes go through, and live subscribers see them too.

    Subscribers are asyncio queues on the daemon's loop. The store never
    waits on a subscriber: a full queue means the browser stopped reading,
    and that subscriber is evicted (EventSource reconnects on its own).

    It subclasses RunStore to *be* one where a RunStore is expected, but every
    method routes to ``_inner`` -- reads included. Inheriting the reads made
    them read ``self.root`` instead, which is only the same file by accident:
    over a NullStore the wrapper answered the web API from whatever ``.poieo``
    the daemon happened to be standing in.
    """

    def __init__(self, inner: RunStore, queue_limit: int = 1000):
        super().__init__(inner.root)
        self._inner = inner
        self._queue_limit = queue_limit
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        # run_id -> flow, learned from run_started, so the SSE endpoint can
        # filter by flow without parsing every payload.
        self.run_flows: dict[str, str] = {}

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_limit)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def _publish(self, record: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                self._subscribers.discard(queue)

    def append(self, event: Event) -> None:
        self._inner.append(event)
        if event.type == "run_started":
            flow = event.data.get("flow")
            if flow:
                self.run_flows[event.run_id] = flow
        self._publish(event.as_dict())

    def record_summary(self, summary: dict[str, Any]) -> None:
        self._inner.record_summary(summary)
        self.run_flows.pop(summary.get("run_id"), None)
        self._publish({"type": "run_summary", **summary})

    # -- reads: the wrapped store answers, never this one --------------------

    def list_runs(self, limit: int = 20, flow: str | None = None) -> list[dict[str, Any]]:
        return self._inner.list_runs(limit=limit, flow=flow)

    def run(self, run_id: str) -> dict[str, Any] | None:
        return self._inner.run(run_id)

    def events(self, run_id: str) -> Iterator[dict[str, Any]]:
        return self._inner.events(run_id)
