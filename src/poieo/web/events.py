"""Fan-out layer: every stored event is also pushed to live subscribers."""

from __future__ import annotations

import asyncio
from typing import Any, Iterator

from ..store import Event, RunStore


class BroadcastStore(RunStore):
    """Wraps a RunStore: writes go through, and live subscribers see them too.

    Never waits on a subscriber -- a full queue means the browser stopped
    reading, so it is evicted and EventSource reconnects on its own.

    Subclasses RunStore to *be* one where one is expected, but **every method
    routes to ``_inner``, reads included**: inheriting the reads would answer
    from ``self.root``, which is only the same file by accident.
    """

    def __init__(self, inner: RunStore, queue_limit: int = 1000):
        super().__init__(inner.root)
        self._inner = inner
        self._queue_limit = queue_limit
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        # run_id -> task, learned from run_started, so the SSE endpoint can
        # filter by task without parsing every payload.
        self.run_tasks: dict[str, str] = {}

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_limit)
        self.add_subscriber(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.remove_subscriber(queue)

    # A queue somebody else made. One reader of a daemon running several
    # projects is one reader, not one per project, so the queue is handed to
    # each store rather than made by it.

    def add_subscriber(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.add(queue)

    def remove_subscriber(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
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
            task = event.data.get("task")
            if task:
                self.run_tasks[event.run_id] = task
        self._publish(event.as_dict())

    def record_summary(self, summary: dict[str, Any]) -> None:
        self._inner.record_summary(summary)
        self.run_tasks.pop(summary.get("run_id"), None)
        self._publish({"type": "run_summary", **summary})

    # -- reads: the wrapped store answers, never this one --------------------

    def list_runs(self, limit: int = 20, task: str | None = None) -> list[dict[str, Any]]:
        return self._inner.list_runs(limit=limit, task=task)

    def summary(self, run_id: str) -> dict[str, Any] | None:
        return self._inner.summary(run_id)

    def events(self, run_id: str) -> Iterator[dict[str, Any]]:
        return self._inner.events(run_id)


class MergedStore(RunStore):
    """Several projects' histories, read as one.

    A daemon running more than one project writes each project's runs under
    its own root -- that is where the project's own `poieo runs` will look for
    them -- and the board asks one question of all of them. This is the seam
    between those two facts.

    Reads only. Writes go to the project whose task made them, which the runner
    already holds; appending here would have to guess, and guessing wrong files
    a run in another project's folder.

    Subclasses RunStore to *be* one where one is expected, the same trick
    :class:`BroadcastStore` plays and for the same reason -- and with the same
    warning: **every method routes to the wrapped stores**, because
    ``self.root`` is only one of several and answering from it would quietly
    return one project's history as though it were all of them.
    """

    def __init__(self, stores: list[RunStore], queue_limit: int = 1000):
        if not stores:
            raise ValueError("a merged store needs at least one store")
        super().__init__(stores[0].root)
        self._stores = list(stores)
        self._queue_limit = queue_limit

    # -- reads ---------------------------------------------------------------

    def list_runs(self, limit: int = 20, task: str | None = None) -> list[dict[str, Any]]:
        """The newest ``limit`` across every project, newest first.

        Each store is asked for its own newest ``limit``, which is the most any
        one of them could contribute to the answer, and the merge sorts on the
        clock. Within a store the index is already in finishing order; across
        stores nothing but the timestamp relates them.
        """
        rows: list[dict[str, Any]] = []
        for store in self._stores:
            rows.extend(store.list_runs(limit=limit, task=task))
        rows.sort(key=lambda row: str(row.get("finished_at") or row.get("started_at") or ""),
                  reverse=True)
        return rows[:limit]

    def summary(self, run_id: str) -> dict[str, Any] | None:
        for store in self._stores:
            found = store.summary(run_id)
            if found is not None:
                return found
        return None

    def events(self, run_id: str) -> Iterator[dict[str, Any]]:
        # Materialised rather than chained: an empty iterator and a store that
        # has never heard of the run look the same from the outside, and the
        # answer is the first store that actually has something to say.
        for store in self._stores:
            found = list(store.events(run_id))
            if found:
                return iter(found)
        return iter(())

    # -- the live feed -------------------------------------------------------

    @property
    def run_tasks(self) -> dict[str, str]:
        """Which task each in-flight run belongs to, across the projects."""
        merged: dict[str, str] = {}
        for store in self._stores:
            merged.update(getattr(store, "run_tasks", {}))
        return merged

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """One queue, fed by every project. A reader is a reader, not N."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_limit)
        for store in self._stores:
            if isinstance(store, BroadcastStore):
                store.add_subscriber(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        for store in self._stores:
            if isinstance(store, BroadcastStore):
                store.remove_subscriber(queue)
