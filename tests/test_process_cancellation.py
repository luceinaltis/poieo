"""An interrupted run owns its processes until they have stopped."""

import asyncio
import sys

import pytest
from conftest import until

from poieo.providers.subscription import _capture


async def test_cancelled_provider_stops_its_child_before_returning(tmp_path):
    started, released, late = (tmp_path / name for name in ["started", "release", "late"])
    child = tmp_path / "child.py"
    child.write_text(
        "import sys,time\nfrom pathlib import Path\n"
        "started,release,late=map(Path,sys.argv[1:])\nstarted.touch()\n"
        "while not release.exists(): time.sleep(.01)\nlate.touch()\n"
    )
    parent = tmp_path / "parent.py"
    parent.write_text("import subprocess,sys\nsubprocess.Popen([sys.executable,*sys.argv[1:]])\n")
    running = asyncio.create_task(
        _capture([sys.executable, str(parent), str(child), str(started), str(released), str(late)], None, 20)
    )
    await until(started.exists, "provider child started")
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    released.touch()
    await asyncio.sleep(0.25)
    assert not late.exists()


async def test_cancelled_container_command_removes_its_borrowed_environment(tmp_path, monkeypatch):
    from poieo.tools import Isolation, docker

    container = docker.Container("task", tmp_path, Isolation(image="mock"))
    container.container_id = "box"
    entered = asyncio.Event()
    removed = []

    async def command(*args, **kwargs):
        if args[0] == "inspect":
            return 0, "true"
        if args[0] == "rm":
            removed.append(args[-1])
            return 0, ""
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(docker, "_docker", command)

    async def work():
        async with docker.DockerExecutor(tmp_path, [], image="mock", container=container) as executor:
            await executor.run_command("wait")

    running = asyncio.create_task(work())
    await asyncio.wait_for(entered.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert removed == ["box"]
    assert container.container_id is None
