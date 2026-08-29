"""Container isolation.

The escape pair at the top is the point of the whole slice: the same command
must fail isolated and succeed unisolated. If both ever pass, the feature is
decorative and these tests are the only thing that would say so.

Real containers, no mocks -- mocking docker would test the mock. The module
skips with a reason when the daemon is unreachable.
"""

import os
import subprocess

import pytest
from conftest import POSIX

from poieo.providers.base import ToolCall
from poieo.tools import DEFAULT_TOOLSETS, LocalExecutor
from poieo.tools.docker import DockerExecutor, docker_available, image_present

IMAGE = os.environ.get("POIEO_TEST_IMAGE", "alpine:3.20")

_ok, _reason = docker_available()
if _ok and not image_present(IMAGE):
    _ok, _reason = False, f"image {IMAGE} is not present; run: docker pull {IMAGE}"

pytestmark = pytest.mark.skipif(not _ok, reason=f"isolation needs docker: {_reason}")

SECRET = "the-host-filesystem"
# The host shell is whatever `run_command` found; the container's is always
# POSIX, which is why only one of these two asks.
HOST_READ_PARENT = "cat ../secret.txt" if POSIX else r"type ..\secret.txt"
BOX_READ_PARENT = "cat ../secret.txt"


def _workdir(tmp_path):
    """A workdir with a secret one level above it -- what must stay unreachable."""
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "secret.txt").write_text(SECRET)
    return work


def _shell(command):
    return ToolCall(id="1", name="run_command", arguments={"command": command})


def _container_exists(container_id):
    done = subprocess.run(
        ["docker", "ps", "-aq", "--no-trunc", "--filter", f"id={container_id}"],
        capture_output=True,
        text=True,
    )
    return container_id in done.stdout


# -- the pair ---------------------------------------------------------------


async def test_a_command_cannot_read_above_the_workdir(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        result = await ex.execute(_shell(BOX_READ_PARENT))
    assert SECRET not in result.text
    assert not result.text.startswith("exit code: 0")


async def test_the_same_command_succeeds_without_isolation(tmp_path):
    """The control. Without this, the test above could pass for the wrong reason."""
    work = _workdir(tmp_path)
    result = await LocalExecutor(work, DEFAULT_TOOLSETS).execute(_shell(HOST_READ_PARENT))
    assert SECRET in result.text


# -- the mount --------------------------------------------------------------


async def test_a_host_write_is_visible_in_the_box(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        await ex.execute(ToolCall(id="1", name="write_file", arguments={"path": "a.txt", "content": "from-host"}))
        result = await ex.execute(_shell("cat a.txt"))
    assert "from-host" in result.text


async def test_a_box_write_is_visible_on_the_host(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        await ex.execute(_shell("echo from-container > b.txt"))
        result = await ex.execute(ToolCall(id="2", name="read_file", arguments={"path": "b.txt"}))
    assert "from-container" in result.text
    # and the host really has the file, not just the executor's view of it
    assert "from-container" in (work / "b.txt").read_text()


async def test_the_workdir_is_a_mount_not_an_empty_volume(tmp_path):
    """A relative or unresolved source makes docker invent a named volume instead."""
    work = _workdir(tmp_path)
    (work / "marker.txt").write_text("x")
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        result = await ex.execute(_shell("ls"))
    assert "marker.txt" in result.text


# -- the network ------------------------------------------------------------


async def test_network_is_off_by_default(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        result = await ex.execute(_shell("ls /sys/class/net"))
    assert "eth0" not in result.text


async def test_bridge_network_can_be_asked_for(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE, network="bridge") as ex:
        result = await ex.execute(_shell("ls /sys/class/net"))
    assert "eth0" in result.text


# -- the lifecycle ----------------------------------------------------------


async def test_the_container_is_gone_after_aexit(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        container_id = ex.container_id
        assert _container_exists(container_id)
    assert not _container_exists(container_id)


async def test_the_container_is_gone_when_the_body_raises(tmp_path):
    work = _workdir(tmp_path)
    container_id = None
    with pytest.raises(RuntimeError, match="boom"):
        async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
            container_id = ex.container_id
            raise RuntimeError("boom")
    assert container_id and not _container_exists(container_id)


async def test_a_timed_out_command_still_tears_down(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        container_id = ex.container_id
        result = await ex.execute(ToolCall(id="1", name="run_command", arguments={"command": "sleep 30", "timeout": 1}))
    assert result.error and "timed out" in result.text
    assert not _container_exists(container_id)


async def test_the_container_carries_a_run_id_label(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE, labels={"poieo.run_id": "r-1"}) as ex:
        done = subprocess.run(
            ["docker", "inspect", "-f", '{{index .Config.Labels "poieo.run_id"}}', ex.container_id],
            capture_output=True,
            text=True,
        )
    assert done.stdout.strip() == "r-1"


# -- the contract -----------------------------------------------------------


async def test_it_declares_the_same_tools_as_the_local_executor(tmp_path):
    work = _workdir(tmp_path)
    local = {d.name for d in LocalExecutor(work, DEFAULT_TOOLSETS).definitions()}
    boxed = {d.name for d in DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE).definitions()}
    assert local == boxed


def test_it_honours_the_selected_toolsets(tmp_path):
    only_files = DockerExecutor(tmp_path, ["files"], image=IMAGE)
    names = {d.name for d in only_files.definitions()}
    assert "read_file" in names and "run_command" not in names


async def test_an_unknown_tool_is_an_error_not_a_crash(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        result = await ex.execute(ToolCall(id="1", name="fly", arguments={}))
    assert result.error and "fly" in result.text


async def test_a_failing_command_reports_its_exit_code(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        result = await ex.execute(_shell("exit 3"))
    assert result.text.startswith("exit code: 3")


async def test_execute_before_entering_is_a_harness_error(tmp_path):
    """Calling execute() without the context manager must not silently run on the host."""
    work = _workdir(tmp_path)
    result = await DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE).execute(_shell("ls"))
    assert result.error


# -- the container: one per task, kept between runs -------------------------------

from datetime import timedelta

from poieo.tools import Isolation
from poieo.tools.docker import Container, ContainerPool, sweep

ISO = Isolation(image=IMAGE)


async def test_two_runs_share_one_box(tmp_path):
    """The lifetime decision, stated as a test: a task's container outlives its runs."""
    work = _workdir(tmp_path)
    container = Container("task-a", work, ISO)
    try:
        first = await container.ensure()
        second = await container.ensure()
        assert first == second
    finally:
        await container.remove()


async def test_a_file_written_by_the_first_run_survives(tmp_path):
    """What reuse is actually for: what run 1 installed is there for run 2."""
    work = _workdir(tmp_path)
    container = Container("task-a", work, ISO)
    try:
        await container.ensure()
        # Written outside the mount, so only the container itself can be keeping it.
        async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE, container=container) as ex:
            await ex.execute(_shell("echo installed > /opt/marker"))
        async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE, container=container) as ex:
            result = await ex.execute(_shell("cat /opt/marker"))
        assert "installed" in result.text
    finally:
        await container.remove()


async def test_an_attached_executor_does_not_remove_the_box(tmp_path):
    """The borrower must not destroy the lender's object."""
    work = _workdir(tmp_path)
    container = Container("task-a", work, ISO)
    try:
        async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE, container=container) as ex:
            container_id = ex.container_id
        assert _container_exists(container_id)
    finally:
        await container.remove()


async def test_a_one_shot_executor_still_removes_its_own(tmp_path):
    work = _workdir(tmp_path)
    async with DockerExecutor(work, DEFAULT_TOOLSETS, image=IMAGE) as ex:
        container_id = ex.container_id
    assert not _container_exists(container_id)


async def test_ensure_restarts_a_box_that_died(tmp_path):
    """Derived state: a machine that slept, or a stray docker rm, must not wedge it."""
    work = _workdir(tmp_path)
    container = Container("task-a", work, ISO)
    try:
        first = await container.ensure()
        subprocess.run(["docker", "rm", "-f", first], capture_output=True)
        second = await container.ensure()
        assert second != first and _container_exists(second)
    finally:
        await container.remove()


async def test_a_changed_image_gets_a_different_box(tmp_path):
    """Not a reconfigure: the keeper keys by settings, so this is the whole
    mechanism and there is nothing else to check."""
    work = _workdir(tmp_path)
    keeper = ContainerPool()
    try:
        assert keeper.get(work, ISO) is not keeper.get(work, Isolation(image="busybox:latest"))
    finally:
        await keeper.aclose()


async def test_remove_is_safe_to_call_twice(tmp_path):
    work = _workdir(tmp_path)
    container = Container("task-a", work, ISO)
    await container.ensure()
    await container.remove()
    await container.remove()


async def test_the_sweep_spares_a_box_in_use(tmp_path):
    work = _workdir(tmp_path)
    container = Container("task-sweep-keep", work, ISO)
    try:
        container_id = await container.ensure()
        await sweep(older_than=timedelta(days=7))
        assert _container_exists(container_id)
    finally:
        await container.remove()


async def test_the_sweep_removes_an_idle_box(tmp_path):
    work = _workdir(tmp_path)
    container = Container("task-sweep-drop", work, ISO)
    container_id = await container.ensure()
    try:
        # Anything created before "now" is older than a zero-length window.
        await sweep(older_than=timedelta(seconds=0))
        assert not _container_exists(container_id)
    finally:
        await container.remove()


# -- one container per (folder, isolation), shared by whatever tasks want it -------


async def test_two_tasks_on_one_folder_share_a_box(tmp_path):
    """The common case: several standing jobs on the same repo."""
    work = _workdir(tmp_path)
    keeper = ContainerPool()
    try:
        a = keeper.get(work, ISO)
        b = keeper.get(work, ISO)
        assert a is b
        assert await a.ensure() == await b.ensure()
    finally:
        await keeper.aclose()


async def test_a_different_image_gets_its_own_box(tmp_path):
    work = _workdir(tmp_path)
    keeper = ContainerPool()
    try:
        a = keeper.get(work, ISO)
        b = keeper.get(work, Isolation(image=IMAGE, network="bridge"))
        assert a is not b
    finally:
        await keeper.aclose()


async def test_a_different_folder_gets_its_own_box(tmp_path):
    keeper = ContainerPool()
    other = tmp_path / "other"
    other.mkdir()
    try:
        assert keeper.get(_workdir(tmp_path), ISO) is not keeper.get(other, ISO)
    finally:
        await keeper.aclose()


async def test_closing_the_keeper_removes_every_box(tmp_path):
    work = _workdir(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    keeper = ContainerPool()
    ids = [await keeper.get(work, ISO).ensure(), await keeper.get(other, ISO).ensure()]
    await keeper.aclose()
    assert not any(_container_exists(i) for i in ids)


async def test_the_sweep_is_what_reclaims_a_hard_kill(tmp_path):
    """A clean shutdown removes every container, so what survives is only what a
    crash left behind -- and that is what the sweep is for."""
    work = _workdir(tmp_path)
    container = Container("orphan", work, ISO)
    container_id = await container.ensure()
    container.container_id = None  # as if the process died holding it
    try:
        await sweep(older_than=timedelta(seconds=0))
        assert not _container_exists(container_id)
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
