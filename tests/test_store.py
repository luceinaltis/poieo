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


def test_list_runs_parses_only_what_it_returns(tmp_path, monkeypatch):
    """The index grows for the daemon's lifetime and the web UI reads it per
    request; parsing all of history to show the last 20 is what made a month
    of uptime cost half a second per call."""
    store = RunStore(tmp_path / "logs")
    for i in range(500):
        store.record_summary({"run_id": f"r{i}", "flow": "loop", "status": "completed"})

    import poieo.store as store_module

    parsed = []
    real = json.loads
    monkeypatch.setattr(store_module.json, "loads", lambda s: parsed.append(1) or real(s))
    rows = store.list_runs(limit=20)
    assert [r["run_id"] for r in rows] == [f"r{499 - i}" for i in range(20)]
    assert len(parsed) <= 25          # the tail, not the history


def test_a_filter_still_finds_older_matches(tmp_path):
    """A rare flow's runs sit deep in the file; the early stop must not
    give up before finding them."""
    store = RunStore(tmp_path / "logs")
    store.record_summary({"run_id": "old", "flow": "rare", "status": "completed"})
    for i in range(100):
        store.record_summary({"run_id": f"r{i}", "flow": "busy", "status": "completed"})
    assert [r["run_id"] for r in store.list_runs(flow="rare")] == ["old"]


def test_a_limit_beyond_history_returns_everything(tmp_path):
    store = RunStore(tmp_path / "logs")
    for i in range(3):
        store.record_summary({"run_id": f"r{i}"})
    assert len(store.list_runs(limit=50)) == 3
