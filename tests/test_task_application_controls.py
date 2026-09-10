"""Decisions and parallel entry points keep one task's work and history intact."""

import asyncio
import json
import os
import subprocess
import threading

import pytest
import yaml
from test_task_application import CHECK_MADE, policy_config, run_once
from test_workspace import git, make_repo, workspace
from typer.testing import CliRunner

from poieo.card import load_card
from poieo.cli import app
from poieo.daemon.changes import check_and_apply
from poieo.workspace import ApplySpec, Workspace


async def test_accepting_old_work_keeps_recent_spending_in_the_limit(tmp_path):
    _, config = policy_config(tmp_path, {"mode": "review"})
    daemon, result = await run_once(config)
    old = {**result.summary(), "finished_at": "2020-01-01", "usage": {"cost": 2}}
    daemon.store.record_summary(old)
    daemon.store.record_summary({**old, "run_id": "recent", "finished_at": "2026-01-02", "usage": {"cost": 9}})
    assert daemon.store.spent_since("2026-01-01", project=config.display_name) == 9
    daemon.runners[0].results.clear()
    assert (await daemon.runners[0].accept_changes())["status"] == "applied"
    assert daemon.store.spent_since("2026-01-01", project=config.display_name) == 9


async def test_stopping_the_daemon_during_manual_verification_keeps_the_original(tmp_path, monkeypatch):
    from poieo.tools import LocalExecutor

    repo, config = policy_config(tmp_path, {"mode": "review", "checks": [CHECK_MADE]})
    daemon, _ = await run_once(config)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def waiting(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(LocalExecutor, "run_command", waiting)
    running = asyncio.create_task(daemon.runners[0].accept_changes())
    await asyncio.wait_for(entered.wait(), 5)
    daemon.stop()
    try:
        await asyncio.wait_for(cancelled.wait(), 2)
    finally:
        running.cancel()
        outcome = await running
    assert outcome["status"] == "blocked"
    assert not (repo / "made.txt").exists()


@pytest.mark.parametrize("choice", ["retry", "pause"])
async def test_answering_an_application_question_keeps_unread_direction(tmp_path, choice):
    from poieo.card import append_journal, read_journal

    _, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "raise SystemExit(1)"']})
    daemon, _ = await run_once(config)
    journal = config.cards_by_task["chores"].journal_path()
    append_journal(journal, "you", "Keep the heading next time")
    assert daemon.runners[0].answer(choice)
    assert "Keep the heading next time" in read_journal(journal).split("What you did before that:")[0]


@pytest.mark.parametrize("partial_failure", [False, True])
async def test_cancelling_a_save_parks_the_work_away_from_future_application(tmp_path, monkeypatch, partial_failure):
    from conftest import until
    from test_task_workspace import NEVER_STOPS, WRITES_NOTHING

    from poieo.daemon import Daemon

    repo, config = policy_config(
        tmp_path,
        {"mode": "auto", "checks": [CHECK_MADE]},
        **({"responses": NEVER_STOPS, "max_turns": 2} if partial_failure else {}),
    )
    daemon = Daemon(config)
    driver = daemon._runners()[0]
    entered, release = threading.Event(), threading.Event()
    commit = driver.workspace.commit

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return commit(*args, **kwargs)

    monkeypatch.setattr(driver.workspace, "commit", delayed)
    running = asyncio.create_task(driver.run_once({}))
    await until(entered.is_set, "save started")
    running.cancel()
    release.set()
    result = await running
    assert result.status in {"aborted", "failed"}
    assert result.steps > 0
    assert driver.workspace.pending() == []
    assert git(repo, "rev-parse", f"refs/poieo/failed/{result.run_id}").strip() == result.change["head"]
    from test_task_workspace import BINDING

    (tmp_path / "b.yaml").write_text(BINDING.format(responses=WRITES_NOTHING))
    restarted = Daemon(config)._runners()[0]
    await restarted.run_once({})
    assert not (repo / "made.txt").exists()


@pytest.mark.parametrize("restart", [False, True])
async def test_a_decision_does_not_mark_unread_user_direction_as_consumed(tmp_path, restart):
    from poieo.card import append_journal, read_journal
    from poieo.daemon import Daemon

    _, config = policy_config(tmp_path, {"mode": "review"})
    daemon, _ = await run_once(config)
    journal = config.cards_by_task["chores"].journal_path()
    append_journal(journal, "you", "Keep the heading next time")
    driver = Daemon(config)._runners()[0] if restart else daemon.runners[0]
    await driver.accept_changes()
    fresh = read_journal(journal).split("What you did before that:")[0]
    assert "Keep the heading next time" in fresh


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("mode", ["review", "auto"])
async def test_cancelling_preparation_does_not_start_tools_or_apply_work(tmp_path, monkeypatch, failed, mode):
    from conftest import until

    from poieo.daemon import Daemon

    repo, config = policy_config(tmp_path, {"mode": mode, "checks": [CHECK_MADE]})
    driver = Daemon(config)._runners()[0]
    entered, release = threading.Event(), threading.Event()
    prepare = driver.workspace.prepare

    def delayed():
        entered.set()
        assert release.wait(10)
        if failed:
            from poieo.workspace import WorkspaceError

            raise WorkspaceError("preparation failed")
        return prepare()

    monkeypatch.setattr(driver.workspace, "prepare", delayed)
    running = asyncio.create_task(driver.run_once({}))
    await until(entered.is_set, "prepare started")
    running.cancel()
    release.set()
    outcome = await asyncio.gather(running, return_exceptions=True)
    assert isinstance(outcome[0], asyncio.CancelledError)
    assert not (repo / "made.txt").exists()
    assert not (driver.workspace.worktree / "made.txt").exists()


def test_a_redirected_private_copy_cannot_reset_the_users_work(tmp_path):
    from poieo.workspace import WorkspaceError

    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    point.prepare()
    (repo / "README.md").write_text("unsaved work")
    point.worktree.rename(point.worktrees / "old-copy")
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(point.worktree), str(repo)], check=True, capture_output=True)
    else:
        point.worktree.symlink_to(repo, target_is_directory=True)
    try:
        with pytest.raises(WorkspaceError, match="private copy"):
            point.prepare()
        assert (repo / "README.md").read_text() == "unsaved work"
    finally:
        point.worktree.rmdir() if os.name == "nt" else point.worktree.unlink()


@pytest.mark.parametrize("pending", [False, True])
def test_task_subfolder_cannot_redirect_work_outside_the_private_copy(tmp_path, pending):
    from poieo.workspace import WorkspaceError

    repo = make_repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "old.txt").write_text("old")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "docs")
    point = workspace(tmp_path, repo / "docs")
    point.prepare()
    if pending:
        (point.worktree / "docs" / "old.txt").write_text("pending")
        point.commit("r1", "pending")
    external = tmp_path / "external"
    external.mkdir()
    (external / "old.txt").write_text("keep my work")
    link = point.worktree / "docs"
    link.rename(point.worktree / "old-docs")
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)], check=True, capture_output=True)
    else:
        link.symlink_to(external, target_is_directory=True)
    try:
        with pytest.raises(WorkspaceError, match="outside its private copy"):
            point.working_folder()
        with pytest.raises(WorkspaceError, match="outside its private copy"):
            point.prepare()
        assert (external / "old.txt").read_text() == "keep my work"
    finally:
        link.rmdir() if os.name == "nt" else link.unlink()


async def test_cancelled_discard_holds_its_copy_until_the_write_and_history_finish(tmp_path, monkeypatch):
    from conftest import until

    from poieo.workspace import WorkspaceError

    _, config = policy_config(tmp_path, {"mode": "review"})
    daemon, result = await run_once(config)
    driver = daemon.runners[0]
    entered, release = threading.Event(), threading.Event()
    discard = driver.workspace.discard

    def delayed(since):
        entered.set()
        assert release.wait(10)
        return discard(since)

    monkeypatch.setattr(driver.workspace, "discard", delayed)
    decision = asyncio.create_task(driver.discard_changes())
    await until(entered.is_set, "discard started")
    decision.cancel()
    await asyncio.sleep(0.05)
    try:
        with pytest.raises(WorkspaceError, match="already running"):
            with driver.workspace.exclusive_run():
                pass
    finally:
        release.set()
        await asyncio.gather(decision, return_exceptions=True)
    assert daemon.store.summary(result.run_id)["application"]["status"] == "discarded"


async def test_accepting_older_work_resolves_the_no_edit_retry_question(tmp_path):
    from test_task_workspace import WRITES_NOTHING
    from test_workspace import do_run

    repo, config = policy_config(
        tmp_path, {"mode": "auto", "checks": ['python -c "raise SystemExit(1)"']}, responses=WRITES_NOTHING
    )
    do_run(Workspace(repo, "chores", config.layout().worktrees()), "older", "made.txt", "hi")
    daemon, result = await run_once(config)
    assert result.change is None
    path = tmp_path / "cards" / "chores.yaml"
    data = yaml.safe_load(path.read_text())
    data["apply"]["checks"] = [CHECK_MADE]
    path.write_text(yaml.safe_dump(data))
    driver = daemon.runners[0]
    assert (await driver.accept_changes())["status"] == "applied"
    assert driver.asking() is None
    assert not driver.holding
    assert daemon.store.summary(result.run_id)["application"]["status"] == "applied"


async def test_accepting_after_a_restart_revises_the_full_result_record(tmp_path):
    from poieo.daemon import Daemon
    from poieo.memory import results_dir

    _, config = policy_config(tmp_path, {"mode": "review", "checks": [CHECK_MADE]})
    _, result = await run_once(config)
    restarted = Daemon(config)
    assert (await restarted._runners()[0].accept_changes())["status"] == "applied"
    record = json.loads((results_dir(config.cards_by_task["chores"].dir) / f"{result.run_id}.json").read_text())
    assert record["application"]["status"] == "applied"
    assert record["outputs"] == result.outputs


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
    assert driver.last_result.status == "completed"
    assert driver.last_result.application["status"] == "applied"
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
    assert driver.last_result.status == "completed"
    assert driver.last_result.application["status"] == "discarded"
    assert driver.asking() is None
    assert daemon.store.summary(result.run_id)["application"]["status"] == "discarded"
    assert not (repo / "made.txt").exists()


@pytest.mark.parametrize("decision", ["accept", "discard"])
async def test_deciding_another_process_change_clears_its_persisted_question(tmp_path, decision):
    from poieo.daemon import Daemon

    _, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "raise SystemExit(1)"']})
    board = Daemon(config)._runners()[0]
    command = Daemon(config)._runners()[0]
    result = await command.run_once({})
    assert result.status == "asking" and board.asking() is None
    path = tmp_path / "cards" / "chores.yaml"
    data = yaml.safe_load(path.read_text())
    data["apply"]["checks"] = [CHECK_MADE]
    path.write_text(yaml.safe_dump(data))
    question = next(config.layout().asking().glob("*.json"))
    stale = question.read_text()
    outcome = await (board.accept_changes() if decision == "accept" else board.discard_changes())
    assert ("accepted" if decision == "accept" else "discarded") in outcome
    assert not question.exists()
    # An interrupted older writer may leave a stale copy; the resolved run wins.
    question.write_text(stale)
    restarted = Daemon(config)._runners()[0]
    assert restarted.asking() is None
    assert not restarted.holding


@pytest.mark.parametrize("choice", ["accept", "pause", "retry"])
async def test_a_stale_question_cannot_replace_the_recorded_application_or_prevent_undo(tmp_path, choice):
    from poieo.daemon import Daemon

    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "raise SystemExit(1)"']})
    stale, other = Daemon(config)._runners()[0], Daemon(config)._runners()[0]
    result = await stale.run_once({})
    path = tmp_path / "cards" / "chores.yaml"
    data = yaml.safe_load(path.read_text())
    data["apply"]["checks"] = ['python -c "pass"']
    path.write_text(yaml.safe_dump(data))
    async with other._private_copy():
        assert not stale.answer("pause")
    applied = await other.accept_changes()
    assert applied["accepted"] == 1
    if choice == "accept":
        assert (await stale.accept_changes())["accepted"] == 0
    else:
        assert not stale.answer(choice)
    assert stale.store.summary(result.run_id)["application"] == applied
    assert stale.last_result.application == applied
    assert stale.asking() is None and not stale.holding
    assert (await stale.undo_changes(result.run_id))["status"] == "applied"
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
