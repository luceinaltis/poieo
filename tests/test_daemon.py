import asyncio
import socket
from datetime import datetime

import httpx
import pytest

from conftest import card, EXAMPLES, at
from poieo.daemon import Daemon, load_config, load_tasks
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
    tasks = load_tasks(config)

    # Cards are read in filename order, and the disabled ones are skipped.
    assert [f.spec.name for f in tasks] == ["keep-tidy", "revision", "triage"]
    assert tasks[-1].graph.name == "support-triage"
    assert config.store_path() == (EXAMPLES / "runs").resolve()


def test_startup_validates_every_flow_up_front(tmp_path):
    (tmp_path / "b.yaml").write_text(
        "providers: {p: {type: mock}}\ndefault: {provider: p, model: m}\n"
    )
    (tmp_path / "g.yaml").write_text("name: g\nentry: a\nnodes: [{id: a, type: agent}]\n")
    card(tmp_path / "cards", "f", f"graph: ../g.yaml\n")
    path = tmp_path / "d.yaml"
    path.write_text(f"binding: b.yaml\ntasks: cards\n")

    # The graph is broken (a model node with no prompt); the daemon must refuse
    # to arm rather than discover this when the trigger first fires.
    with pytest.raises(SpecError, match="requires a prompt"):
        load_tasks(load_config(path))


def _keyed_config(tmp_path, variable="POIEO_TEST_KEY"):
    (tmp_path / "b.yaml").write_text(
        f"providers: {{p: {{type: openai_compatible, base_url: 'http://x/v1', "
        f"api_key_env: {variable}}}}}\n"
        "default: {provider: p, model: m}\n"
    )
    (tmp_path / "g.yaml").write_text(
        "name: g\nentry: a\nnodes: [{id: a, type: agent, prompt: hi}]\n"
    )
    card(tmp_path / "cards", "f", f"graph: ../g.yaml\n")
    path = tmp_path / "d.yaml"
    path.write_text(f"binding: b.yaml\ntasks: cards\n")
    return path


def test_startup_refuses_a_flow_whose_credential_is_missing(tmp_path, monkeypatch):
    """A binding naming an environment variable the machine does not have is
    a misconfiguration, and it must surface where `poieo daemon` starts --
    not eight turns into the run its trigger fires at 3am."""
    monkeypatch.delenv("POIEO_TEST_KEY", raising=False)
    with pytest.raises(SpecError, match=r"task 'f'.*\$POIEO_TEST_KEY is not set"):
        load_tasks(load_config(_keyed_config(tmp_path)))


def test_startup_accepts_the_same_flow_once_the_key_is_there(tmp_path, monkeypatch):
    monkeypatch.setenv("POIEO_TEST_KEY", "sk-whatever")
    assert len(load_tasks(load_config(_keyed_config(tmp_path)))) == 1


def test_a_disabled_flow_can_still_be_listed_without_its_key(tmp_path, monkeypatch):
    """The same rule check_isolation follows: a task that is not going to run
    must still show up in `poieo tasks`, or the check gets in the way of the
    fix it is asking for."""
    monkeypatch.delenv("POIEO_TEST_KEY", raising=False)
    path = _keyed_config(tmp_path)
    card(tmp_path / "cards", "f", f"graph: ../g.yaml\nenabled: false\n")
    assert len(load_tasks(load_config(path), enabled_only=False)) == 1


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
        "name: g\nentry: a\nnodes: [{id: a, type: agent, prompt: hi}]\n"
    )
    card(tmp_path / "cards", "f", f"graph: ../g.yaml\n")
    path = tmp_path / "d.yaml"
    path.write_text(f"binding: b.yaml\ntasks: cards\n")

    assert len(load_tasks(load_config(path))) == 1


async def test_daemon_runs_every_task_once_and_shuts_down(sample_project, monkeypatch):
    config = load_config(sample_project / "poieo.yaml")
    for task in config.tasks:
        task.trigger.max_iterations = 1

    daemon = Daemon(config, store=NullStore())
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=10)

    assert {r.task for r in results} == {"keep-tidy", "revision", "triage"}
    assert all(r.status == "completed" for r in results)
    assert daemon.pools  # a pool was created...
    assert not any(p.instantiated() for p in daemon.pools.values())  # ...and closed


async def test_carry_state_feeds_the_next_iteration(sample_project):
    config = load_config(sample_project / "poieo.yaml")
    config.tasks = [f for f in config.tasks if f.name == "revision"]
    config.tasks[0].trigger.max_iterations = 2
    config.tasks[0].trigger.cooldown = 0

    daemon = Daemon(config, store=NullStore())
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=10)

    assert [r.iteration for r in results] == [1, 2]
    assert results[1].state.get("latest_draft")


async def test_results_are_a_window_not_a_history(sample_project, monkeypatch):
    """A RunResult carries the run's whole outputs and state. A loop task with
    no cooldown makes one per fire for the daemon's lifetime, and only the tail
    is ever read -- last_result by the API, one pass's worth by --once."""
    from poieo.daemon import service

    monkeypatch.setattr(service, "RESULTS_KEPT", 3)

    config = load_config(sample_project / "poieo.yaml")
    config.tasks = [f for f in config.tasks if f.name == "triage"]
    config.tasks[0].trigger = TriggerSpec(type="loop", max_iterations=8)

    daemon = Daemon(config, store=NullStore())
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=30)

    runner = daemon.runners[0]
    assert len(runner.results) == 3  # the window, not all eight
    assert runner.last_result is results[-1]
    assert runner.last_result.iteration == 8


async def test_flow_runner_exposes_live_status(sample_project):
    config = load_config(sample_project / "poieo.yaml")
    config.tasks = [f for f in config.tasks if f.name == "triage"]
    config.tasks[0].trigger.max_iterations = 1

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


async def test_daemon_with_web_port_wraps_store_and_serves(sample_project):
    config = load_config(sample_project / "poieo.yaml")
    config.tasks = [f for f in config.tasks if f.name == "triage"]
    # Two iterations 30s apart: the first fires at once, then the runner sits on
    # the second, so the API is still up when the poll below lands.
    config.tasks[0].trigger.max_iterations = 2

    port = _free_port()
    daemon = Daemon(config, store=NullStore(), web_port=port)
    serve_task = asyncio.create_task(daemon.serve(install_signals=False))

    try:
        async with httpx.AsyncClient() as client:
            deadline = asyncio.get_running_loop().time() + 5
            response = None
            while asyncio.get_running_loop().time() < deadline:
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/api/tasks")
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
        "name: g" + chr(10) + "entry: a" + chr(10) + "nodes: [{id: a, type: agent, prompt: p}]" + chr(10)
    )
    (tmp_path / "project").mkdir()
    card(tmp_path / "cards", "f", "graph: ../g.yaml\nfolder: ../project\n")
    path = tmp_path / "d.yaml"
    path.write_text("binding: b.yaml" + chr(10) + "tasks: cards" + chr(10))

    config = load_config(path)

    assert config.tasks[0].workdir == str(tmp_path / "project")
    # resolved against the config file, not whatever cwd the daemon started in
    assert config.workdir_path(config.tasks[0]) == tmp_path / "project"


def test_flow_workdir_is_optional(tmp_path):
    # Reads the shipped project rather than a copy: this asks where a workdir
    # resolves *to*, and the answer is spelled against EXAMPLES below. Nothing
    # here runs, so nothing here writes.
    config = load_config(EXAMPLES / "poieo.yaml")
    by_name = {f.name: f for f in config.tasks}

    # A task that only moves text says nothing about the filesystem...
    assert by_name["triage"].workdir is None
    assert config.workdir_path(by_name["triage"]) is None
    # ...while one that touches a project says where.
    assert config.workdir_path(by_name["chores"]) == (EXAMPLES / "..").resolve()


# -- isolation preflight: fail at launch, not at 3am -------------------------


def _isolated_config(tmp_path, image="python:3.12-slim", count=1):
    body = [
        f"binding: {EXAMPLES / 'models/mock.yaml'}",
        f"store: {tmp_path / 'logs'}",
        "tasks: cards",
    ]
    for i in range(count):
        card(
            tmp_path / "cards",
            f"t{i}",
            f"graph: {EXAMPLES / 'tasks/support-triage.graph.yaml'}\n"
            "trigger: {type: interval, every: 60s}\n"
            "isolation:\n"
            f"  image: {image}\n",
        )
    path = tmp_path / "poieo.yaml"
    path.write_text("\n".join(body) + "\n")
    return load_config(path)


def test_a_flow_with_isolation_fails_to_load_without_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "poieo.tools.docker.docker_available", lambda: (False, "docker is not on PATH")
    )
    with pytest.raises(SpecError, match="docker is not on PATH"):
        load_tasks(_isolated_config(tmp_path))


def test_a_missing_image_names_the_pull_command(tmp_path, monkeypatch):
    monkeypatch.setattr("poieo.tools.docker.docker_available", lambda: (True, ""))
    monkeypatch.setattr("poieo.tools.docker.image_present", lambda image: False)
    with pytest.raises(SpecError, match="docker pull python:3.12-slim"):
        load_tasks(_isolated_config(tmp_path))


def test_the_same_image_is_only_checked_once(tmp_path, monkeypatch):
    """Ten tasks sharing an image must not cost ten inspects."""
    seen = []
    monkeypatch.setattr("poieo.tools.docker.docker_available", lambda: (True, ""))
    monkeypatch.setattr(
        "poieo.tools.docker.image_present", lambda image: seen.append(image) or True
    )
    load_tasks(_isolated_config(tmp_path, count=5))
    assert seen == ["python:3.12-slim"]


def test_flows_without_isolation_never_touch_docker(tmp_path, monkeypatch):
    """No ping at all: a machine without docker must not slow down or fail."""
    def boom():
        raise AssertionError("docker was probed for a task that never asked")

    monkeypatch.setattr("poieo.tools.docker.docker_available", boom)
    config = tmp_path / "poieo.yaml"
    card(
        tmp_path / "cards",
        "plain",
        f"graph: {EXAMPLES / 'tasks/support-triage.graph.yaml'}\n"
        f"trigger: {{type: interval, every: 60s}}\n",
    )
    config.write_text(
        f"binding: {EXAMPLES / 'models/mock.yaml'}\n"
        f"store: {tmp_path / 'logs'}\n"
        "tasks: cards\n"
    )
    assert len(load_tasks(load_config(config))) == 1


def test_a_disabled_flow_is_not_preflighted(tmp_path, monkeypatch):
    """Its image may well be gone; it is not going to run."""
    monkeypatch.setattr(
        "poieo.tools.docker.docker_available", lambda: (False, "docker is not on PATH")
    )
    config = _isolated_config(tmp_path)
    config.tasks[0].enabled = False
    assert load_tasks(config) == []


def test_listing_a_disabled_isolated_flow_does_not_preflight(tmp_path, monkeypatch):
    """`poieo tasks` loads disabled tasks too. It must still list one whose
    image is gone -- that task is not going to run."""
    monkeypatch.setattr(
        "poieo.tools.docker.docker_available", lambda: (False, "docker is not on PATH")
    )
    config = _isolated_config(tmp_path)
    config.tasks[0].enabled = False
    assert len(load_tasks(config, enabled_only=False)) == 1


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
        f"binding: {EXAMPLES / 'models/mock.yaml'}\n"
        f"store: {tmp_path / 'logs'}\n"
        "tasks: tasks\n"
    )
    return load_config(path)


async def test_a_task_can_actually_reach_its_sibling(tmp_path):
    """The whole chain: daemon builds the postbox, the tool writes the journal."""
    config = _tasks_config(tmp_path)
    daemon = Daemon(config)
    runner = next(r for r in daemon._runners() if r.name == "build-docs")
    container = runner.tool_context.postbox
    assert container is not None
    assert container.sender == "build-docs"
    assert "check-links" in container.recipients


def test_the_roster_reaches_the_generated_prompt(tmp_path):
    config = _tasks_config(tmp_path)
    task = next(f for f in load_tasks(config) if f.spec.name == "build-docs")
    system = task.graph.nodes[0].system or ""
    assert "check-links" in system
    assert "build-docs" not in system.split("Other tasks")[-1]


def test_a_task_without_notes_gets_no_postbox(tmp_path):
    config = _tasks_config(tmp_path, tools="[files, shell]")
    daemon = Daemon(config)
    assert all(r.tool_context.postbox is None for r in daemon._runners())


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
        at(tmp_path).longterm().mkdir(parents=True, exist_ok=True)
    config = tmp_path / "poieo.yaml"
    config.write_text(
        f"binding: {(EXAMPLES / 'models/mock.yaml').as_posix()}\n"
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
        f"prompt: go\nbinding: {(EXAMPLES / 'models/mock.yaml').as_posix()}\n",
        encoding="utf-8",
    )
    config = tmp_path / "poieo.yaml"
    config.write_text("tasks: tasks/\nlearn: 1h\n", encoding="utf-8")
    with pytest.raises(SpecError, match="binding"):
        load_config(config)


def test_an_unconfigured_daemon_never_learns(tmp_path):
    daemon = Daemon(_learning_config(tmp_path, learn=""))
    assert daemon._ready_to_learn(daemon.projects[0]) is False


def test_a_bare_tasks_folder_inside_a_project_joins_it(tmp_path):
    """`poieo daemon tasks/` names which cards to run. It was never a claim
    about where the project begins, so a marker above still answers that --
    and the cards keep one history and one memory rather than starting a
    second set beside themselves."""
    from poieo.daemon.config import config_for_tasks_folder

    config = _learning_config(tmp_path)  # writes a poieo.yaml at tmp_path
    bare = config_for_tasks_folder(tmp_path / "tasks")

    assert bare.base_dir == tmp_path.resolve()
    assert bare.layout().memory() == tmp_path.resolve() / "memory"
    # ...and the model it reads with, not just where things live: joining
    # a project halfway is a rule nobody can hold in their head.
    assert bare.binding == config.binding
    assert [task.name for task in bare.tasks] == ["one"]


def test_a_bare_tasks_folder_outside_a_project_is_its_own(tmp_path):
    from poieo.daemon.config import config_for_tasks_folder

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tmp_path / "project").mkdir()
    (tasks / "one.yaml").write_text(
        f"name: one\nfolder: {(tmp_path / 'project').as_posix()}\n"
        f"prompt: go\nbinding: {(EXAMPLES / 'models/mock.yaml').as_posix()}\n",
        encoding="utf-8",
    )
    bare = config_for_tasks_folder(tasks)
    assert bare.layout().memory() == tasks.resolve() / "memory"


def test_a_daemon_without_a_memory_folder_never_learns(tmp_path):
    daemon = Daemon(_learning_config(tmp_path, memory=False))
    assert daemon._ready_to_learn(daemon.projects[0]) is False


def test_half_an_opt_in_says_so_at_load(tmp_path, caplog):
    """`learn:` set and no folder to learn into is the one way this feature
    dies quietly -- the key says learn, nothing is kept, and a person waits a
    week for entries that were never coming. A warning, not a failure: the
    folder is still the opt-in, and a config key must not conjure it."""
    with caplog.at_level("WARNING", logger="poieo.daemon"):
        _learning_config(tmp_path, memory=False)

    said = " ".join(caplog.messages)
    assert "nothing will be learned" in said
    assert "longterm" in said


def test_a_folder_that_is_kept_warns_about_nothing(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="poieo.daemon"):
        _learning_config(tmp_path, memory=True)
    assert not [m for m in caplog.messages if "nothing will be learned" in m]


def test_a_busy_daemon_waits_its_turn(tmp_path):
    from types import SimpleNamespace

    daemon = Daemon(_learning_config(tmp_path))
    assert daemon._ready_to_learn(daemon.projects[0]) is True

    daemon.runners = [SimpleNamespace(status="running")]
    assert daemon._ready_to_learn(daemon.projects[0]) is False


async def test_a_failing_pass_never_takes_the_daemon_down(tmp_path, monkeypatch):
    import poieo.daemon.service as service
    from poieo.binding import load_binding
    from poieo.providers import ProviderPool

    daemon = Daemon(_learning_config(tmp_path))

    async def blow_up(*args, **kwargs):
        raise RuntimeError("the model ate the homework")

    monkeypatch.setattr(service, "learn_pass", blow_up)
    spec = load_binding(EXAMPLES / "models/mock.yaml")
    async with ProviderPool(spec) as pool:
        await daemon._learn_once(daemon.projects[0], spec, pool)  # must not raise


def test_a_zero_learn_interval_fails_at_load(tmp_path):
    # _sleep_or_cancel(0) returns without awaiting; a zero interval would
    # spin the loop without ever yielding and starve the whole daemon.
    with pytest.raises(SpecError, match="positive"):
        _learning_config(tmp_path, "learn: 0s\n")


# -- the way down ------------------------------------------------------------


async def test_a_background_task_that_blew_up_says_so_on_the_way_down(caplog):
    """Shutdown used to swallow whatever a background task raised. A learning
    pass that failed at 3am went down with the daemon without leaving a word."""
    from poieo.daemon.service import _stopped

    async def explode():
        raise RuntimeError("the learner fell over")

    task = asyncio.ensure_future(explode())
    with caplog.at_level("WARNING", logger="poieo.daemon"):
        await _stopped(task, "learning pass")

    assert "learning pass stopped badly" in caplog.text
    assert "the learner fell over" in caplog.text


async def test_a_background_task_that_will_not_stop_is_left_behind(caplog, monkeypatch):
    """Five seconds, then the daemon carries on: the pools and the containers below
    still have to be closed."""
    from poieo.daemon import service

    monkeypatch.setattr(service, "SHUTDOWN_GRACE", 0.05)

    async def forever():
        await asyncio.Event().wait()

    task = asyncio.ensure_future(forever())
    with caplog.at_level("WARNING", logger="poieo.daemon"):
        await service._stopped(task, "web server")

    assert "web server did not stop" in caplog.text


async def test_a_background_task_that_stopped_cleanly_says_nothing(caplog):
    from poieo.daemon.service import _stopped

    async def tidy():
        return None

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        await _stopped(asyncio.ensure_future(tidy()), "learning pass")

    assert caplog.text == ""


def test_a_schedule_reads_back_the_way_it_was_written():
    """`every: 30m` shown as `every 1800s` makes a reader do arithmetic to
    check their own config. The number is the same fact either way; only one
    of them can be checked at a glance.

    This string is what `poieo tasks`, `poieo tasks` and `poieo validate`
    print, what the board labels a task with, and what every run records as
    the reason it fired -- so it is worth being readable in one place.
    """
    said = lambda every: TriggerSpec(type="interval", every=every).build().describe

    assert said("30m") == "every 30m"
    assert said("1h") == "every 1h"
    assert said("2h") == "every 2h"
    assert said("1d") == "every 1d"
    assert said("45s") == "every 45s"
    # Not a whole number of the larger unit: seconds is the honest answer.
    assert said(90) == "every 90s"
    assert said("1.5h") == "every 90m"
