import asyncio
import socket
from datetime import datetime

import httpx
import pytest

from conftest import EXAMPLES
from poieo.daemon import Daemon, load_config, load_flows
from poieo.daemon.cron import CronSchedule
from poieo.daemon.service import _ensure_port_free
from poieo.daemon.triggers import TriggerSpec, parse_duration
from poieo.errors import SpecError
from poieo.store import NullStore
from poieo.web.events import BroadcastStore


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


async def test_interval_trigger_never_fires_twice_inside_one_period():
    """A timer that wakes early must not turn one tick into two.

    The grid is derived from elapsed time, so a wake-up a hair before the tick
    it was aimed at used to select that same tick again and fire immediately.
    """
    trigger = TriggerSpec(type="interval", every="0.05s", max_iterations=20).build()
    loop = asyncio.get_running_loop()

    stamps = []
    cancel = asyncio.Event()
    async for _ in trigger.fires(cancel):
        stamps.append(loop.time())

    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(stamps) == 20
    # One period is 50ms; the floor allows for a wake-up up to 20ms early,
    # which a coarse Windows timer really does produce.
    assert min(gaps) >= 0.03, gaps


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


def _keyed_config(tmp_path, variable="POIEO_TEST_KEY"):
    (tmp_path / "b.yaml").write_text(
        f"providers: {{p: {{type: openai_compatible, base_url: 'http://x/v1', "
        f"api_key_env: {variable}}}}}\n"
        "default: {provider: p, model: m}\n"
    )
    (tmp_path / "g.yaml").write_text(
        "name: g\nentry: a\nnodes: [{id: a, type: llm, prompt: hi}]\n"
    )
    path = tmp_path / "d.yaml"
    path.write_text("binding: b.yaml\nflows: [{name: f, graph: g.yaml}]\n")
    return path


def test_startup_refuses_a_flow_whose_credential_is_missing(tmp_path, monkeypatch):
    """A binding naming an environment variable the machine does not have is
    a misconfiguration, and it must surface where `poieo daemon` starts --
    not eight turns into the run its trigger fires at 3am."""
    monkeypatch.delenv("POIEO_TEST_KEY", raising=False)
    with pytest.raises(SpecError, match=r"flow 'f'.*\$POIEO_TEST_KEY is not set"):
        load_flows(load_config(_keyed_config(tmp_path)))


def test_startup_accepts_the_same_flow_once_the_key_is_there(tmp_path, monkeypatch):
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-whatever")
    assert len(load_flows(load_config(_keyed_config(tmp_path)))) == 1


def test_a_credential_no_role_asks_for_is_not_demanded(tmp_path, monkeypatch):
    """Only what the graph will actually call. An extra endpoint declared in
    the binding but bound to no role must not hold the daemon down."""
    monkeypatch.delenv("POIEO_TEST_KEY", raising=False)
    (tmp_path / "b.yaml").write_text(
        "providers:\n"
        "  used: {type: mock}\n"
        "  spare: {type: openai_compatible, base_url: 'http://x/v1', "
        "api_key_env: POIEO_TEST_KEY}\n"
        "default: {provider: used, model: m}\n"
    )
    (tmp_path / "g.yaml").write_text(
        "name: g\nentry: a\nnodes: [{id: a, type: llm, prompt: hi}]\n"
    )
    path = tmp_path / "d.yaml"
    path.write_text("binding: b.yaml\nflows: [{name: f, graph: g.yaml}]\n")

    assert len(load_flows(load_config(path))) == 1


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


async def test_results_are_a_window_not_a_history(monkeypatch):
    """A RunResult carries the run's whole outputs and state. A loop flow with
    no cooldown makes one per fire for the daemon's lifetime, and only the tail
    is ever read -- last_result by the API, one pass's worth by --once."""
    from poieo.daemon import service

    monkeypatch.setattr(service, "RESULTS_KEPT", 3)

    config = load_config(EXAMPLES / "poieo.yaml")
    config.flows = [f for f in config.flows if f.name == "triage"]
    config.flows[0].trigger = TriggerSpec(type="loop", max_iterations=8)

    daemon = Daemon(config, store=NullStore())
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=30)

    runner = daemon.runners[0]
    assert len(runner.results) == 3  # the window, not all eight
    assert runner.last_result is results[-1]
    assert runner.last_result.iteration == 8


async def test_flow_runner_exposes_live_status():
    config = load_config(EXAMPLES / "poieo.yaml")
    config.flows = [f for f in config.flows if f.name == "triage"]
    config.flows[0].trigger.max_iterations = 1

    daemon = Daemon(config, store=NullStore())
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=10)

    runner = daemon.runners[0]
    assert runner.status == "waiting"
    assert runner.current_run_id is None
    assert runner.last_result is results[-1]
    assert runner.last_result.status == "completed"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_ensure_port_free_raises_when_taken():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        with pytest.raises(SpecError, match=str(port)):
            _ensure_port_free("127.0.0.1", port)


def test_ensure_port_free_passes_on_free_port():
    port = _free_port()  # released above; must not raise
    _ensure_port_free("127.0.0.1", port)


async def test_daemon_with_web_port_wraps_store_and_serves():
    config = load_config(EXAMPLES / "poieo.yaml")
    config.flows = [f for f in config.flows if f.name == "triage"]
    # Two iterations 30s apart: the first fires at once, then the runner sits on
    # the second, so the API is still up when the poll below lands.
    config.flows[0].trigger.max_iterations = 2

    port = _free_port()
    daemon = Daemon(config, store=NullStore(), web_port=port)
    serve_task = asyncio.create_task(daemon.serve(install_signals=False))

    try:
        async with httpx.AsyncClient() as client:
            deadline = asyncio.get_running_loop().time() + 5
            response = None
            while asyncio.get_running_loop().time() < deadline:
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/api/flows")
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.1)

        assert response is not None and response.status_code == 200
        assert "triage" in response.text
    finally:
        daemon.cancel.set()

    results = await asyncio.wait_for(serve_task, timeout=30)
    assert isinstance(daemon.store, BroadcastStore)
    assert results  # the run finished and the server shut down cleanly


def test_flow_spec_accepts_a_workdir(tmp_path):
    (tmp_path / "b.yaml").write_text(
        "providers: {p: {type: mock}}" + chr(10) + "default: {provider: p, model: m}" + chr(10)
    )
    (tmp_path / "g.yaml").write_text(
        "name: g" + chr(10) + "entry: a" + chr(10) + "nodes: [{id: a, type: llm, prompt: p}]" + chr(10)
    )
    path = tmp_path / "d.yaml"
    path.write_text(
        "binding: b.yaml" + chr(10)
        + "flows: [{name: f, graph: g.yaml, workdir: project}]" + chr(10)
    )

    config = load_config(path)

    assert config.flows[0].workdir == "project"
    # resolved against the config file, not whatever cwd the daemon started in
    assert config.workdir_path(config.flows[0]) == tmp_path / "project"


def test_flow_workdir_is_optional(tmp_path):
    config = load_config(EXAMPLES / "poieo.yaml")
    by_name = {f.name: f for f in config.flows}

    # A flow that only moves text says nothing about the filesystem...
    assert by_name["triage"].workdir is None
    assert config.workdir_path(by_name["triage"]) is None
    # ...while one that touches a project says where.
    assert config.workdir_path(by_name["chores"]) == (EXAMPLES / "..").resolve()


# -- isolation preflight: fail at launch, not at 3am -------------------------


def _isolated_config(tmp_path, image="python:3.12-slim", count=1):
    body = [
        f"binding: {EXAMPLES / 'bindings/mock.yaml'}",
        f"store: {tmp_path / 'logs'}",
        "flows:",
    ]
    for i in range(count):
        body += [
            f"  - name: t{i}",
            f"    graph: {EXAMPLES / 'graphs/support-triage.yaml'}",
            "    trigger: {type: interval, every: 60s}",
            "    isolation:",
            f"      image: {image}",
        ]
    path = tmp_path / "poieo.yaml"
    path.write_text("\n".join(body) + "\n")
    return load_config(path)


def test_a_flow_with_isolation_fails_to_load_without_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "poieo.tools.docker.docker_available", lambda: (False, "docker is not on PATH")
    )
    with pytest.raises(SpecError, match="docker is not on PATH"):
        load_flows(_isolated_config(tmp_path))


def test_a_missing_image_names_the_pull_command(tmp_path, monkeypatch):
    monkeypatch.setattr("poieo.tools.docker.docker_available", lambda: (True, ""))
    monkeypatch.setattr("poieo.tools.docker.image_present", lambda image: False)
    with pytest.raises(SpecError, match="docker pull python:3.12-slim"):
        load_flows(_isolated_config(tmp_path))


def test_the_same_image_is_only_checked_once(tmp_path, monkeypatch):
    """Ten tasks sharing an image must not cost ten inspects."""
    seen = []
    monkeypatch.setattr("poieo.tools.docker.docker_available", lambda: (True, ""))
    monkeypatch.setattr(
        "poieo.tools.docker.image_present", lambda image: seen.append(image) or True
    )
    load_flows(_isolated_config(tmp_path, count=5))
    assert seen == ["python:3.12-slim"]


def test_flows_without_isolation_never_touch_docker(tmp_path, monkeypatch):
    """No ping at all: a machine without docker must not slow down or fail."""
    def boom():
        raise AssertionError("docker was probed for a flow that never asked")

    monkeypatch.setattr("poieo.tools.docker.docker_available", boom)
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {EXAMPLES / 'bindings/mock.yaml'}\n"
        f"store: {tmp_path / 'logs'}\n"
        "flows:\n"
        "  - name: plain\n"
        f"    graph: {EXAMPLES / 'graphs/support-triage.yaml'}\n"
        "    trigger: {type: interval, every: 60s}\n"
    )
    assert len(load_flows(load_config(config))) == 1


def test_a_disabled_flow_is_not_preflighted(tmp_path, monkeypatch):
    """Its image may well be gone; it is not going to run."""
    monkeypatch.setattr(
        "poieo.tools.docker.docker_available", lambda: (False, "docker is not on PATH")
    )
    config = _isolated_config(tmp_path)
    config.flows[0].enabled = False
    assert load_flows(config) == []


def test_listing_a_disabled_isolated_flow_does_not_preflight(tmp_path, monkeypatch):
    """`poieo flows` loads disabled flows too. It must still list one whose
    image is gone -- that flow is not going to run."""
    monkeypatch.setattr(
        "poieo.tools.docker.docker_available", lambda: (False, "docker is not on PATH")
    )
    config = _isolated_config(tmp_path)
    config.flows[0].enabled = False
    assert len(load_flows(config, enabled_only=False)) == 1


# -- notes reach the tasks that can send them --------------------------------


def _tasks_config(tmp_path, tools="[files, notes]"):
    folder = tmp_path / "tasks"
    folder.mkdir()
    (tmp_path / "work").mkdir()
    for name in ("build-docs", "check-links"):
        (folder / f"{name}.yaml").write_text(
            f"name: {name}\nfolder: ../work\nprompt: go\ntools: {tools}\n"
        )
    path = tmp_path / "poieo.yaml"
    path.write_text(
        f"binding: {EXAMPLES / 'bindings/mock.yaml'}\n"
        f"store: {tmp_path / 'logs'}\n"
        "tasks: tasks\n"
        "flows: []\n"
    )
    return load_config(path)


async def test_a_task_can_actually_reach_its_sibling(tmp_path):
    """The whole chain: daemon builds the postbox, the tool writes the journal."""
    config = _tasks_config(tmp_path)
    daemon = Daemon(config)
    runner = next(r for r in daemon._runners() if r.name == "build-docs")
    box = runner.hands.postbox
    assert box is not None
    assert box.sender == "build-docs"
    assert "check-links" in box.recipients


def test_the_roster_reaches_the_generated_prompt(tmp_path):
    config = _tasks_config(tmp_path)
    flow = next(f for f in load_flows(config) if f.spec.name == "build-docs")
    system = flow.graph.nodes[0].system or ""
    assert "check-links" in system
    assert "build-docs" not in system.split("Other tasks")[-1]


def test_a_task_without_notes_gets_no_postbox(tmp_path):
    config = _tasks_config(tmp_path, tools="[files, shell]")
    daemon = Daemon(config)
    assert all(r.hands.postbox is None for r in daemon._runners())


# -- learning while nothing else is running ----------------------------------


def _learning_config(tmp_path, learn="learn: 1h\n", memory=True):
    (tmp_path / "project").mkdir(exist_ok=True)
    tasks = tmp_path / "tasks"
    tasks.mkdir(exist_ok=True)
    (tasks / "one.yaml").write_text(
        f"name: one\nfolder: {(tmp_path / 'project').as_posix()}\nprompt: go\n",
        encoding="utf-8",
    )
    if memory:
        (tasks / "memory").mkdir(exist_ok=True)
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\n"
        f"store: {(tmp_path / 'logs').as_posix()}\n"
        "tasks: tasks/\n" + learn,
        encoding="utf-8",
    )
    return load_config(config)


def test_a_learn_interval_parses_and_a_bad_one_fails_at_load(tmp_path):
    assert _learning_config(tmp_path, "learn: 1d\n").learn == "1d"
    with pytest.raises(SpecError):
        _learning_config(tmp_path, "learn: soon\n")


def test_learning_needs_the_daemon_default_binding(tmp_path):
    (tmp_path / "project").mkdir()
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "one.yaml").write_text(
        f"name: one\nfolder: {(tmp_path / 'project').as_posix()}\n"
        f"prompt: go\nbinding: {(EXAMPLES / 'bindings/mock.yaml').as_posix()}\n",
        encoding="utf-8",
    )
    config = tmp_path / "poieo.yaml"
    config.write_text("tasks: tasks/\nlearn: 1h\n", encoding="utf-8")
    with pytest.raises(SpecError, match="binding"):
        load_config(config)


def test_an_unconfigured_daemon_never_learns(tmp_path):
    daemon = Daemon(_learning_config(tmp_path, learn=""))
    assert daemon._ready_to_learn() is False


def test_a_daemon_without_a_memory_folder_never_learns(tmp_path):
    daemon = Daemon(_learning_config(tmp_path, memory=False))
    assert daemon._ready_to_learn() is False


def test_a_busy_daemon_waits_its_turn(tmp_path):
    from types import SimpleNamespace

    daemon = Daemon(_learning_config(tmp_path))
    assert daemon._ready_to_learn() is True

    daemon.runners = [SimpleNamespace(status="running")]
    assert daemon._ready_to_learn() is False


async def test_a_failing_pass_never_takes_the_daemon_down(tmp_path, monkeypatch):
    import poieo.daemon.service as service
    from poieo.binding import load_binding
    from poieo.providers import ProviderPool

    daemon = Daemon(_learning_config(tmp_path))

    async def blow_up(*args, **kwargs):
        raise RuntimeError("the model ate the homework")

    monkeypatch.setattr(service, "learn_pass", blow_up)
    spec = load_binding(EXAMPLES / "bindings/mock.yaml")
    async with ProviderPool(spec) as pool:
        await daemon._learn_once(spec, pool)  # must not raise


def test_a_zero_learn_interval_fails_at_load(tmp_path):
    # _sleep_or_cancel(0) returns without awaiting; a zero interval would
    # spin the loop without ever yielding and starve the whole daemon.
    with pytest.raises(SpecError, match="positive"):
        _learning_config(tmp_path, "learn: 0s\n")
