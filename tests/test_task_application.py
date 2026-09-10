"""Delegation applies only the checked work the task was allowed to change."""

import pytest
import yaml
from test_task_workspace import build, events_of, run_once
from test_workspace import do_run, git, head, make_repo, workspace

from poieo.card import expand, load_card
from poieo.daemon import load_config
from poieo.errors import SpecError


def policy_config(tmp_path, policy, **kwargs):
    repo, config = build(tmp_path, **kwargs)
    path = tmp_path / "cards" / "chores.yaml"
    data = yaml.safe_load(path.read_text())
    data["apply"] = policy
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return repo, load_config(tmp_path / "d.yaml")


CHECK_MADE = 'python -c "from pathlib import Path; assert Path(\'made.txt\').read_text() == \'hi\'"'


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
    checks = ['python -c "from pathlib import Path; assert Path(\'value.txt\').read_text() == '
              'Path(\'requirement.txt\').read_text()"']

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
    import shutil

    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]})
    shutil.rmtree(repo / ".git")
    with pytest.raises(SpecError, match="Git"):
        await run_once(config)
    assert not (repo / "made.txt").exists()
