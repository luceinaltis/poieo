"""BroadcastStore: events go to the file store and to live subscribers."""

import asyncio

from poieo.store import Event, NullStore, RunStore
from poieo.web.events import BroadcastStore


def make_store(tmp_path):
    return BroadcastStore(RunStore(tmp_path / ".poieo"))


async def test_events_write_through_and_broadcast(tmp_path):
    store = make_store(tmp_path)
    queue = store.subscribe()

    event = Event(run_id="r1", type="run_started", data={"task": "triage"})
    store.append(event)

    record = queue.get_nowait()
    assert record["type"] == "run_started"
    assert record["run_id"] == "r1"
    # written through to the JSONL store too
    assert [e["type"] for e in store.events("r1")] == ["run_started"]
    # task learned for SSE filtering
    assert store.run_tasks["r1"] == "triage"


async def test_summary_broadcast_and_run_flow_cleanup(tmp_path):
    store = make_store(tmp_path)
    queue = store.subscribe()
    store.append(Event(run_id="r1", type="run_started", data={"task": "triage"}))
    queue.get_nowait()

    store.record_summary({"run_id": "r1", "task": "triage", "status": "completed"})
    record = queue.get_nowait()
    assert record["type"] == "run_summary"
    assert record["status"] == "completed"
    assert "r1" not in store.run_tasks
    assert store.list_runs()[0]["run_id"] == "r1"


async def test_slow_subscriber_is_evicted_not_blocking(tmp_path):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"), queue_limit=2)
    slow = store.subscribe()
    fast = store.subscribe()

    for i in range(4):  # two more than the slow queue can hold
        store.append(Event(run_id="r1", type="node_started", data={"step": i}))
        fast.get_nowait()

    # the slow queue filled at 2 and was dropped; publishing never raised
    assert slow.qsize() == 2
    store.append(Event(run_id="r1", type="node_started", data={"step": 9}))
    assert slow.qsize() == 2          # no longer receiving
    assert fast.get_nowait()["data"]["step"] == 9


async def test_reads_answer_from_the_wrapped_store(tmp_path, monkeypatch):
    """The wrapper is a decorator, so every read must reach the store it was
    handed. `poieo daemon --no-log` wraps a NullStore, and the web API served
    over it used to answer from whatever `./.poieo` happened to hold."""
    monkeypatch.chdir(tmp_path)
    RunStore(".poieo").append(Event(run_id="r1", type="run_started"))
    RunStore(".poieo").record_summary({"run_id": "r1", "task": "f", "status": "completed"})

    store = BroadcastStore(NullStore())
    assert store.list_runs() == []
    assert store.summary("r1") is None
    assert list(store.events("r1")) == []


async def test_unsubscribe_stops_delivery(tmp_path):
    store = make_store(tmp_path)
    queue = store.subscribe()
    store.unsubscribe(queue)
    store.append(Event(run_id="r1", type="node_started"))
    assert queue.qsize() == 0
