"""Wear that decays and cannot run away.

Runtime emphasis, never meaning: a corrupt or missing file reads as empty,
a failure to write is logged and swallowed, and the fan cap plus decay make
runaway impossible by construction.
"""

from conftest import at
from datetime import datetime, timedelta, timezone

from poieo.strength import FAN_CAP, reinforce, strengths


def _pair(a, b):
    return frozenset((a, b))


def test_a_reinforced_pair_carries_more_than_a_fresh_one(tmp_path):
    reinforce(tmp_path, [("a", "b")])
    reinforce(tmp_path, [("a", "b")])
    reinforce(tmp_path, [("a", "c")])

    strength = strengths(tmp_path)
    assert strength[_pair("a", "b")] > strength[_pair("a", "c")] > 0


def test_an_untouched_weight_decays_toward_nothing(tmp_path):
    t0 = datetime(2026, 8, 24, tzinfo=timezone.utc)
    reinforce(tmp_path, [("a", "b")], now=t0)

    fresh = strengths(tmp_path, now=t0)[_pair("a", "b")]
    faded = strengths(tmp_path, now=t0 + timedelta(days=90)).get(_pair("a", "b"), 0.0)
    assert faded < fresh / 4


def test_the_fan_cap_holds_an_entrys_total_however_often_it_is_fed(tmp_path):
    t0 = datetime(2026, 8, 24, tzinfo=timezone.utc)
    for i in range(40):
        reinforce(tmp_path, [("hub", f"n{i % 8}")], now=t0)

    strength = strengths(tmp_path, now=t0)
    total = sum(value for pair, value in strength.items() if "hub" in pair)
    assert total <= FAN_CAP + 1e-6


def test_a_corrupt_file_reads_as_empty_and_heals_on_next_reinforce(tmp_path):
    store = at(tmp_path).cache()
    store.mkdir(parents=True)
    at(tmp_path).strength().write_text("{ not json", encoding="utf-8")

    assert strengths(tmp_path) == {}
    reinforce(tmp_path, [("a", "b")])
    assert strengths(tmp_path)[_pair("a", "b")] > 0


def test_wear_never_raises(tmp_path):
    # A file where the store's folder should be: every write must fail,
    # quietly.
    at(tmp_path).memory().write_text("in the way", encoding="utf-8")
    reinforce(tmp_path, [("a", "b")])  # must not raise
    assert strengths(tmp_path) == {}


def test_a_slug_containing_the_delimiter_is_refused_quietly(tmp_path):
    reinforce(tmp_path, [("a|b", "c")])
    assert strengths(tmp_path) == {}


def test_one_bad_entry_does_not_wipe_the_rest(tmp_path):
    import json

    reinforce(tmp_path, [("a", "b")])
    path = at(tmp_path).strength()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pairs"]["x|y"] = {"w": "abc", "at": "2026-08-24T00:00:00+00:00"}
    path.write_text(json.dumps(data), encoding="utf-8")

    assert _pair("a", "b") in strengths(tmp_path)
