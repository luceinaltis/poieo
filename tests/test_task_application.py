"""Delegation applies only the checked work the task was allowed to change."""

import asyncio

import pytest
import yaml
from test_task_workspace import build, events_of
from test_workspace import do_run, git, head, make_repo, workspace

from poieo.card import expand, load_card
from poieo.daemon import Daemon, load_config
from poieo.errors import SpecError


def policy_config(tmp_path, policy, **kwargs):
    repo, config = build(tmp_path, **kwargs)
    path = tmp_path / "cards" / "chores.yaml"
    data = yaml.safe_load(path.read_text())
    data["apply"] = policy
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return repo, load_config(tmp_path / "d.yaml")


CHECK_MADE = "python -c \"from pathlib import Path; assert Path('made.txt').read_text() == 'hi'\""


async def run_once(config):
    daemon = Daemon(config, on_run=lambda _task, _result: daemon.stop())
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=30)
    return daemon, results[0]


def test_automatic_application_requires_a_real_verification_command(tmp_path):
    with pytest.raises(SpecError, match="needs at least one verification command"):
        policy_config(tmp_path, {"mode": "auto"})


@pytest.mark.parametrize("path", ["../outside", "/outside", "C:/outside", ".git/config", "docs/../../outside"])
def test_allowed_paths_cannot_escape_the_task_folder(tmp_path, path):
    with pytest.raises(SpecError, match="allowed path must"):
        policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE], "paths": [path]})


def test_a_card_carries_the_same_application_settings_after_expansion(tmp_path):
    policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE], "paths": ["made.txt"]})
    card = load_card(tmp_path / "cards" / "chores.yaml")
    task, _ = expand(card)
    assert task.apply == card.apply
    assert task.apply.mode == "auto"


async def test_successful_work_is_checked_and_automatically_applied(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE], "paths": ["made.txt"]})
    before = head(repo, "HEAD")

    daemon, result = await run_once(config)

    assert (repo / "made.txt").read_text() == "hi"
    assert result.application["status"] == "applied"
    assert result.application["before"] == before
    assert result.application["checks"][0]["exit_code"] == 0
    assert daemon.runners[0].workspace.pending() == []
    assert any(event["type"] == "run_application" for event in events_of(config, result.run_id))


async def test_failed_verification_keeps_work_and_holds_only_its_task(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "raise SystemExit(1)"']})
    before = head(repo, "HEAD")

    daemon, result = await run_once(config)

    assert head(repo, "HEAD") == before
    assert not (repo / "made.txt").exists()
    assert daemon.runners[0].workspace.pending()
    assert result.application["status"] == "blocked"
    assert result.application["checks"][0]["exit_code"] == 1
    assert result.status == "asking"
    assert daemon.runners[0].holding
    assert daemon.runners[0].asking().run_id == result.run_id


async def test_changes_outside_the_allowed_paths_are_not_applied(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE], "paths": ["docs"]})

    _, result = await run_once(config)

    assert result.application["outside_scope"] == ["made.txt"]
    assert not (repo / "made.txt").exists()


async def test_review_mode_keeps_verified_work_for_the_user(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "review", "checks": [CHECK_MADE]})

    daemon, result = await run_once(config)

    assert not (repo / "made.txt").exists()
    assert result.application["status"] == "review"
    assert result.application["checks"][0]["exit_code"] == 0
    assert not daemon.runners[0].holding


async def test_checks_see_the_combined_result_not_just_the_task_copy(tmp_path):
    from poieo.daemon.changes import check_and_apply
    from poieo.workspace import ApplySpec

    repo = make_repo(tmp_path)
    (repo / "value.txt").write_text("old", encoding="utf-8")
    git(repo, "add", "value.txt")
    git(repo, "commit", "-m", "initial value")
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "requirement.txt", "old")
    (repo / "value.txt").write_text("new", encoding="utf-8")
    git(repo, "commit", "-am", "another task changed the value")
    checks = [
        "python -c \"from pathlib import Path; assert Path('value.txt').read_text() == "
        "Path('requirement.txt').read_text()\""
    ]

    result = await check_and_apply(point, ApplySpec(mode="auto", checks=checks))

    assert result["status"] == "blocked"
    assert result["checks"][0]["exit_code"] == 1
    assert not (repo / "requirement.txt").exists()


async def test_revoking_permission_during_verification_prevents_application(tmp_path):
    from poieo.daemon.changes import check_and_apply
    from poieo.workspace import ApplySpec

    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "hi")

    result = await check_and_apply(point, ApplySpec(mode="auto", checks=[CHECK_MADE]), authorized=lambda: False)

    assert result["status"] == "review"
    assert not (repo / "made.txt").exists()


async def test_automatic_application_refuses_an_unprotected_folder_before_running(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]})
    (repo / ".git").rename(repo / ".git-kept")
    with pytest.raises(SpecError, match="Git"):
        await run_once(config)
    assert not (repo / "made.txt").exists()


async def test_an_allowed_folder_includes_its_children_but_not_similar_names(tmp_path):
    from poieo.daemon.changes import check_and_apply
    from poieo.workspace import ApplySpec

    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    point.prepare()
    (point.worktree / "docs").mkdir()
    do_run(point, "r1", "docs/note.txt", "hi")
    result = await check_and_apply(point, ApplySpec(mode="auto", paths=["docs"], checks=['python -c "pass"']))
    assert result["status"] == "applied"
    do_run(point, "r2", "docs-private.txt", "private")
    result = await check_and_apply(point, ApplySpec(mode="auto", paths=["docs"], checks=['python -c "pass"']))
    assert result["outside_scope"] == ["docs-private.txt"]


async def test_review_does_not_report_a_check_that_rewrote_the_candidate_as_verified(tmp_path):
    from poieo.daemon.changes import check_and_apply
    from poieo.workspace import ApplySpec

    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "hi")
    result = await check_and_apply(
        point, ApplySpec(checks=["python -c \"from pathlib import Path; Path('made.txt').write_text('different')\""])
    )
    assert result["status"] == "blocked"
    assert result["verification_changed"] == ["made.txt"]


async def test_automatic_work_never_falls_back_to_editing_the_original(tmp_path, monkeypatch):
    from poieo.workspace import Workspace, WorkspaceError

    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]})

    def broken_copy(self):
        raise WorkspaceError("could not prepare a private copy")

    monkeypatch.setattr(Workspace, "prepare", broken_copy)
    daemon, result = await run_once(config)
    assert not (repo / "made.txt").exists()
    assert result.status == "asking"
    assert result.application["status"] == "blocked"
    assert daemon.runners[0].holding


async def test_manual_application_still_obeys_the_tasks_checks(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "review", "checks": ['python -c "raise SystemExit(1)"']})
    daemon, result = await run_once(config)
    outcome = await daemon.runners[0].accept_changes(result.change["head"])
    assert outcome["status"] == "blocked"
    assert "accepted" not in outcome
    assert not (repo / "made.txt").exists()


async def test_cancelling_preparation_waits_for_its_copy_and_cleans_it_up(tmp_path, monkeypatch):
    import threading

    from poieo.daemon.changes import check_and_apply
    from poieo.workspace import ApplySpec

    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "hi")
    started, release = threading.Event(), threading.Event()
    prepare = point.prepare_accept

    def slow_prepare(through=None):
        prepared = prepare(through)
        started.set()
        assert release.wait(5)
        return prepared

    monkeypatch.setattr(point, "prepare_accept", slow_prepare)
    job = asyncio.create_task(check_and_apply(point, ApplySpec(mode="auto", checks=[CHECK_MADE])))
    assert await asyncio.to_thread(started.wait, 5)
    job.cancel()
    release.set()
    result = await asyncio.wait_for(job, 5)
    assert result["status"] == "blocked"
    assert not (repo / "made.txt").exists()
    assert not list(point.worktrees.glob(".review-*"))


async def test_stop_interrupts_an_active_verification_command(tmp_path):
    from conftest import until

    from poieo.daemon.changes import check_and_apply
    from poieo.workspace import ApplySpec

    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "hi")
    cancel = asyncio.Event()
    check = "python -c \"from pathlib import Path; import time; Path('checking').touch(); time.sleep(60)\""
    job = asyncio.create_task(check_and_apply(point, ApplySpec(mode="auto", checks=[check]), cancel=cancel))
    await until(lambda: any(point.worktrees.glob(".review-*/checking")), "verification started")
    cancel.set()
    result = await asyncio.wait_for(job, 5)
    assert result["status"] == "blocked"
    assert not (repo / "made.txt").exists()
    assert not list(point.worktrees.glob(".review-*"))


async def test_application_rechecks_when_another_task_finishes_first(tmp_path, monkeypatch):
    from poieo.daemon.changes import check_and_apply
    from poieo.workspace import ApplySpec

    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "hi")
    apply = point.apply_prepared
    calls = []

    def competing_apply(prepared):
        calls.append(prepared.base)
        if len(calls) == 1:
            (repo / "other.txt").write_text("another task")
            git(repo, "add", "other.txt")
            git(repo, "commit", "-m", "another task finished first")
        return apply(prepared)

    monkeypatch.setattr(point, "apply_prepared", competing_apply)
    result = await check_and_apply(point, ApplySpec(mode="auto", checks=[CHECK_MADE]))
    assert result["status"] == "applied"
    assert len(calls) == 2 and calls[0] != calls[1]
    assert (repo / "other.txt").read_text() == "another task"


def test_cli_uses_the_same_automatic_verification_before_touching_the_project(tmp_path):
    import json

    from typer.testing import CliRunner

    from poieo.cli import app

    repo, _ = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "raise SystemExit(1)"']})
    result = CliRunner().invoke(app, ["run", str(tmp_path / "cards" / "chores.yaml"),
        "--binding", str(tmp_path / "b.yaml"), "--json"])
    assert result.exit_code == 1
    record = json.loads(result.stdout)
    assert record["application"]["status"] == "blocked"
    assert not (repo / "made.txt").exists()
