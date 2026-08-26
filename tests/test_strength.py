"""Wear that decays and cannot run away.

Runtime emphasis, never meaning: a corrupt or missing file reads as empty,
a failure to write is logged and swallowed, and the fan cap plus decay make
runaway impossible by construction.
"""

from conftest import at
from datetime import datetime, timedelta, timezone

from poieo.strength import FAN_CAP, wear, wear_of


def _pair(a, b):
    return frozenset((a, b))


def test_a_reinforced_pair_carries_more_than_a_fresh_one(tmp_path):
    wear(tmp_path, [("a", "b")])
    wear(tmp_path, [("a", "b")])
    wear(tmp_path, [("a", "c")])

    worn = wear_of(tmp_path)
    assert worn[_pair("a", "b")] > worn[_pair("a", "c")] > 0


def test_an_untouched_weight_decays_toward_nothing(tmp_path):
    t0 = datetime(2026, 8, 24, tzinfo=timezone.utc)
    wear(tmp_path, [("a", "b")], now=t0)

    fresh = wear_of(tmp_path, now=t0)[_pair("a", "b")]
    faded = wear_of(tmp_path, now=t0 + timedelta(days=90)).get(_pair("a", "b"), 0.0)
    assert faded < fresh / 4


def test_the_fan_cap_holds_an_entrys_total_however_often_it_is_fed(tmp_path):
    t0 = datetime(2026, 8, 24, tzinfo=timezone.utc)
    for i in range(40):
        wear(tmp_path, [("hub", f"n{i % 8}")], now=t0)

    worn = wear_of(tmp_path, now=t0)
    total = sum(value for pair, value in worn.items() if "hub" in pair)
    assert total <= FAN_CAP + 1e-6


def test_a_corrupt_file_reads_as_empty_and_heals_on_next_wear(tmp_path):
    store = at(tmp_path).cache()
    store.mkdir(parents=True)
    at(tmp_path).strength().write_text("{ not json", encoding="utf-8")

    assert wear_of(tmp_path) == {}
    wear(tmp_path, [("a", "b")])
    assert wear_of(tmp_path)[_pair("a", "b")] > 0


def test_wear_never_raises(tmp_path):
    # A file where the store's folder should be: every write must fail,
    # quietly.
    at(tmp_path).memory().write_text("in the way", encoding="utf-8")
    wear(tmp_path, [("a", "b")])  # must not raise
    assert wear_of(tmp_path) == {}


def test_a_slug_containing_the_delimiter_is_refused_quietly(tmp_path):
    wear(tmp_path, [("a|b", "c")])
    assert wear_of(tmp_path) == {}


def test_one_bad_entry_does_not_wipe_the_rest(tmp_path):
    import json

    wear(tmp_path, [("a", "b")])
    path = at(tmp_path).strength()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pairs"]["x|y"] = {"w": "abc", "at": "2026-08-24T00:00:00+00:00"}
    path.write_text(json.dumps(data), encoding="utf-8")

    assert _pair("a", "b") in wear_of(tmp_path)
