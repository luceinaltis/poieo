import asyncio
from datetime import datetime

import pytest

from conftest import EXAMPLES
from poieo.daemon import Daemon, load_config, load_flows
from poieo.daemon.cron import CronSchedule
from poieo.daemon.triggers import TriggerSpec, parse_duration
from poieo.errors import SpecError
from poieo.store import NullStore


@pytest.mark.parametrize(
    "value,seconds", [("30s", 30), ("5m", 300), ("2h", 7200), ("1d", 86400), (90, 90)]
)
def test_parse_duration(value, seconds):
    assert parse_duration(value) == seconds


def test_parse_duration_rejects_junk():
    with pytest.raises(SpecError):
        parse_duration("soon")


@pytest.mark.parametrize(
    "expression,now,expected",
    [
        ("*/5 * * * *", datetime(2026, 8, 20, 12, 3), datetime(2026, 8, 20, 12, 5)),
        ("0 9 * * mon-fri", datetime(2026, 8, 21, 10, 0), datetime(2026, 8, 24, 9, 0)),
        ("30 2 1 * *", datetime(2026, 8, 20, 12, 0), datetime(2026, 9, 1, 2, 30)),
        ("0 12 29 2 *", datetime(2026, 8, 20, 12, 0), datetime(2028, 2, 29, 12, 0)),
    ],
)
def test_cron_next_fire(expression, now, expected):
    schedule = CronSchedule(expression)
    assert schedule.next_after(now) == expected
    assert schedule.matches(expected)


@pytest.mark.parametrize(
    "expression", ["* * * *", "60 * * * *", "*/0 * * * *", "0 0 * * xyz"]
)
def test_cron_rejects_bad_expressions(expression):
    with pytest.raises(SpecError):
        CronSchedule(expression)


def test_cron_or_semantics_when_both_day_fields_are_restricted():
    # Standard cron: "1st of the month OR any Monday".
    schedule = CronSchedule("0 0 1 * mon")
    assert schedule.matches(datetime(2026, 9, 1))       # a Tuesday, but the 1st
    assert schedule.matches(datetime(2026, 9, 7))       # a Monday
    assert not schedule.matches(datetime(2026, 9, 8))


async def collect(trigger, limit, cancel=None):
    cancel = cancel or asyncio.Event()
    fires = []
    async for fire in trigger.fires(cancel):
        fires.append(fire)
        if len(fires) >= limit:
            cancel.set()
    return fires


async def test_loop_trigger_stops_at_max_iterations():
    trigger = TriggerSpec(type="loop", max_iterations=3).build()
    fires = await collect(trigger, 10)
    assert [f.iteration for f in fires] == [1, 2, 3]


async def test_interval_trigger_fires_immediately_then_periodically():
    trigger = TriggerSpec(
        type="interval", every="0.05s", max_iterations=3, run_at_start=True
    ).build()
    started = asyncio.get_running_loop().time()
    fires = await collect(trigger, 10)
    elapsed = asyncio.get_running_loop().time() - started

    assert len(fires) == 3
    # First fire is immediate, so three fires span roughly two intervals.
    assert 0.08 <= elapsed < 0.5


async def test_manual_trigger_never_fires_on_its_own():
    trigger = TriggerSpec(type="manual").build()
    cancel = asyncio.Event()
    task = asyncio.create_task(collect(trigger, 1, cancel))
    await asyncio.sleep(0.05)
    cancel.set()
    assert await asyncio.wait_for(task, timeout=1) == []


def test_config_resolves_paths_relative_to_itself(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # cwd is deliberately somewhere else
    config = load_config(EXAMPLES / "poieo.yaml")
    flows = load_flows(config)

    assert [f.spec.name for f in flows] == ["triage", "revision"]  # disabled one skipped
    assert flows[0].graph.name == "support-triage"
    assert config.store_path() == (EXAMPLES / ".poieo").resolve()


def test_config_rejects_duplicate_flow_names(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(
        "binding: b.yaml\n"
        "flows:\n"
        "  - {name: a, graph: g.yaml}\n"
        "  - {name: a, graph: g.yaml}\n"
    )
    with pytest.raises(SpecError, match="duplicate flow names"):
        load_config(path)


def test_startup_validates_every_flow_up_front(tmp_path):
    (tmp_path / "b.yaml").write_text(
        "providers: {p: {type: mock}}\ndefault: {provider: p, model: m}\n"
    )
    (tmp_path / "g.yaml").write_text("name: g\nentry: a\nnodes: [{id: a, type: llm}]\n")
    path = tmp_path / "d.yaml"
    path.write_text("binding: b.yaml\nflows: [{name: f, graph: g.yaml}]\n")

    # The graph is broken (an llm node with no prompt); the daemon must refuse
    # to arm rather than discover this when the trigger first fires.
    with pytest.raises(SpecError, match="requires a prompt"):
        load_flows(load_config(path))


async def test_daemon_runs_every_flow_once_and_shuts_down(tmp_path, monkeypatch):
    config = load_config(EXAMPLES / "poieo.yaml")
    for flow in config.flows:
        flow.trigger.max_iterations = 1

    daemon = Daemon(config, store=NullStore())
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=10)

    assert {r.flow for r in results} == {"triage", "revision"}
    assert all(r.status == "completed" for r in results)
    assert daemon.pools  # a pool was created...
    assert not any(p.instantiated() for p in daemon.pools.values())  # ...and closed


async def test_carry_state_feeds_the_next_iteration():
    config = load_config(EXAMPLES / "poieo.yaml")
    config.flows = [f for f in config.flows if f.name == "revision"]
    config.flows[0].trigger.max_iterations = 2
    config.flows[0].trigger.cooldown = 0

    daemon = Daemon(config, store=NullStore())
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=10)

    assert [r.iteration for r in results] == [1, 2]
    assert results[1].state.get("latest_draft")
