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


def test_null_store_reads_nothing_either(tmp_path, monkeypatch):
    """A store that drops every write must not answer reads from somebody
    else's history. `poieo run --no-log` in a folder that already has a
    `.poieo/` would otherwise report runs it never recorded."""
    monkeypatch.chdir(tmp_path)
    RunStore(".poieo").record_summary({"run_id": "r1", "flow": "f", "status": "completed"})

    store = NullStore()
    assert store.list_runs() == []
    assert store.run("r1") is None
    assert list(store.events("r1")) == []


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


def test_events_are_not_fsynced_one_by_one(tmp_path, monkeypatch):
    """An agent run emits an event per model turn and per tool call, and every
    fsync stalls the loop the daemon shares with the web server. Durability is
    bought once, at the run boundary, where the index line lands."""
    import poieo.store as store_module

    synced = []
    monkeypatch.setattr(store_module.os, "fsync", lambda fd: synced.append(fd))
    store = RunStore(tmp_path / "logs")
    for _ in range(5):
        store.append(Event(run_id="r1", type="node_turn"))
    assert synced == []
    store.record_summary({"run_id": "r1", "status": "completed"})
    assert len(synced) == 1


def test_run_returns_the_newest_and_stops_there(tmp_path, monkeypatch):
    """run() fires on every diff view and every accept click; scanning the
    whole index per click grows with daemon uptime."""
    store = RunStore(tmp_path / "logs")
    store.record_summary({"run_id": "r1", "status": "failed"})
    store.record_summary({"run_id": "r1", "status": "completed"})  # re-recorded
    for i in range(50):
        store.record_summary({"run_id": f"busy{i}", "status": "completed"})

    import poieo.store as store_module

    parsed = []
    real = json.loads
    monkeypatch.setattr(store_module.json, "loads", lambda s: parsed.append(1) or real(s))
    row = store.run("r1")
    assert row["status"] == "completed"  # the newest record still wins
    assert len(parsed) == 1  # the answer, not everything before or after it


def test_a_damaged_line_never_costs_the_lines_around_it(tmp_path):
    """A run log is appended to by a daemon and openable by the user, so a
    blank line, a half-written last one, or something that is not a mapping
    at all are all things that happen. None is worth refusing to answer over
    -- and a bare list used to reach a caller that would ask it for a key."""
    store = RunStore(tmp_path / "logs")
    store.record_summary({"run_id": "r1", "flow": "chores"})
    store.record_summary({"run_id": "r2", "flow": "chores"})
    with store.index_path.open("a", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write("[1, 2, 3]\n")
        handle.write('{"run_id": "half-writ')  # a torn tail, no newline

    assert [row["run_id"] for row in store.list_runs()] == ["r2", "r1"]
    assert store.run("r1")["flow"] == "chores"
    assert store.run("nope") is None


def test_events_survive_the_same_damage(tmp_path):
    store = RunStore(tmp_path / "logs")
    store.append(Event(run_id="r1", type="run_started"))
    with (store.runs_dir / "r1.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n[1, 2]\nnot json at all\n")
    store.append(Event(run_id="r1", type="run_finished"))

    assert [e["type"] for e in store.events("r1")] == ["run_started", "run_finished"]


def test_list_runs_reads_the_tail_not_the_file(tmp_path, monkeypatch):
    """Parsing was already lazy; the read was not. read_text loads a month of
    history into memory to show twenty rows."""
    from pathlib import Path

    store = RunStore(tmp_path / "logs")
    for i in range(30):
        store.record_summary({"run_id": f"r{i}"})

    def boom(self, *args, **kwargs):
        raise AssertionError("list_runs materialized the whole index")

    monkeypatch.setattr(Path, "read_text", boom)
    rows = store.list_runs(limit=5)
    assert [r["run_id"] for r in rows] == [f"r{29 - i}" for i in range(5)]


def test_a_row_larger_than_one_read_block_still_parses(tmp_path):
    """Reading backwards works in fixed-size blocks; a summary row bigger than
    one block (and full of multi-byte text) must reassemble intact."""
    store = RunStore(tmp_path / "logs")
    store.record_summary({"run_id": "big", "note": "메모 " * 40_000})
    store.record_summary({"run_id": "after"})
    rows = store.list_runs(limit=2)
    assert [r["run_id"] for r in rows] == ["after", "big"]
    assert rows[1]["note"].startswith("메모")
