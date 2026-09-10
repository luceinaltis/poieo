"""Decisions and parallel entry points keep one task's work and history intact."""

import asyncio

import pytest
import yaml
from test_task_application import CHECK_MADE, policy_config, run_once
from test_workspace import git, make_repo, workspace
from typer.testing import CliRunner

from poieo.card import load_card
from poieo.cli import app
from poieo.daemon.changes import check_and_apply
from poieo.workspace import ApplySpec, Workspace


def test_cli_cannot_open_a_copy_another_runner_is_still_working_in(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "review"})
    point = Workspace(repo, "chores", config.layout().worktrees())
    point.prepare()
    (point.worktree / "README.md").write_text("unfinished work")
    with point.exclusive_run():
        result = CliRunner().invoke(
            app, ["run", str(tmp_path / "cards" / "chores.yaml"), "--binding", str(tmp_path / "b.yaml"), "--json"]
        )
    assert result.exit_code == 1
    assert (point.worktree / "README.md").read_text() == "unfinished work"


def test_eject_keeps_automatic_application_and_its_restrictions(tmp_path):
    _, _ = policy_config(tmp_path, {"mode": "auto", "paths": ["made.txt"], "checks": [CHECK_MADE]})
    path = tmp_path / "cards" / "chores.yaml"
    data = yaml.safe_load(path.read_text())
    data.pop("graph")
    data["prompt"] = "write made.txt"
    path.write_text(yaml.safe_dump(data))
    before = load_card(path).apply
    result = CliRunner().invoke(app, ["eject", str(path)])
    assert result.exit_code == 0, result.output
    assert load_card(path).apply == before


async def test_manual_acceptance_updates_the_question_and_recorded_application(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "raise SystemExit(1)"']})
    daemon, result = await run_once(config)
    path = tmp_path / "cards" / "chores.yaml"
    data = yaml.safe_load(path.read_text())
    data["apply"]["checks"] = [CHECK_MADE]
    path.write_text(yaml.safe_dump(data))
    driver = daemon.runners[0]
    accepted = await driver.accept_changes(result.change["head"])
    assert accepted["status"] == "applied"
    assert driver.asking() is None
    assert not driver.holding
    assert daemon.store.summary(result.run_id)["application"]["status"] == "applied"
    assert not list(config.layout().asking().glob("*.json"))
    assert (repo / "made.txt").read_text() == "hi"


async def test_manual_discard_resolves_the_blocked_question_without_applying(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "raise SystemExit(1)"']})
    daemon, result = await run_once(config)
    driver = daemon.runners[0]
    await driver.discard_changes(result.change["head"])
    assert driver.asking() is None
    assert daemon.store.summary(result.run_id)["application"]["status"] == "discarded"
    assert not (repo / "made.txt").exists()


async def test_removing_the_last_file_in_the_task_folder_still_has_a_check_directory(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "old.txt").write_text("old")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "docs")
    point = workspace(tmp_path, repo / "docs")
    point.prepare()
    (point.worktree / "docs" / "old.txt").unlink()
    point.commit("r1", "remove obsolete document")
    outcome = await check_and_apply(point, ApplySpec(mode="auto", checks=['python -c "pass"']))
    assert outcome["status"] == "applied"
    assert not (repo / "docs" / "old.txt").exists()


async def test_cancelling_a_shell_stops_orphaned_descendants_before_returning(tmp_path):
    from poieo.tools.shell import _POSIX_SHELL, run_here

    if not _POSIX_SHELL and __import__("os").name == "nt":
        pytest.skip("this reproduction uses POSIX job syntax")
    command = (
        "(python -c \"import time; from pathlib import Path; Path('started').touch(); "
        "time.sleep(4); Path('escaped').touch()\" &)"
    )
    running = asyncio.create_task(run_here(tmp_path, command))
    from conftest import until

    await until(lambda: (tmp_path / "started").exists(), "child started")
    await asyncio.sleep(0.1)
    running.cancel()
    started = asyncio.get_running_loop().time()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert asyncio.get_running_loop().time() - started < 2
    assert not (tmp_path / "escaped").exists()
