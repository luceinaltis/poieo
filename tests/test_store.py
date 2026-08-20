import json

from poieo.store import Event, NullStore, RunStore


def test_events_and_index_round_trip(tmp_path):
    store = RunStore(tmp_path / "logs")
    store.append(Event(run_id="r1", type="run_started", data={"graph": "g"}))
    store.append(Event(run_id="r1", type="node_finished", node_id="a", data={"output": "x"}))
    store.record_summary({"run_id": "r1", "flow": "f", "status": "completed"})
    store.record_summary({"run_id": "r2", "flow": "other", "status": "failed"})

    events = list(store.events("r1"))
    assert [e["type"] for e in events] == ["run_started", "node_finished"]
    assert events[1]["node_id"] == "a"

    assert [r["run_id"] for r in store.list_runs()] == ["r2", "r1"]  # newest first
    assert [r["run_id"] for r in store.list_runs(flow="f")] == ["r1"]
    assert store.events("missing") is not None
    assert list(store.events("missing")) == []


def test_non_json_values_are_coerced_rather_than_crashing(tmp_path):
    store = RunStore(tmp_path / "logs")
    store.append(Event(run_id="r1", type="t", data={"when": object()}))
    line = json.loads((store.runs_dir / "r1.jsonl").read_text())
    assert isinstance(line["data"]["when"], str)


def test_a_truncated_line_does_not_break_reads(tmp_path):
    store = RunStore(tmp_path / "logs")
    store.record_summary({"run_id": "r1", "status": "completed"})
    with store.index_path.open("a") as handle:
        handle.write('{"run_id": "r2", "sta\n')  # a crash mid-write
    assert [r["run_id"] for r in store.list_runs()] == ["r1"]


def test_null_store_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = NullStore()
    store.append(Event(run_id="r1", type="t"))
    store.record_summary({"run_id": "r1"})
    assert list(tmp_path.iterdir()) == []
