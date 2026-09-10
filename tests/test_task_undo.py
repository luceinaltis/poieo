"""Undo applies a verified inverse change without removing later work."""

from test_task_application import policy_config, run_once
from test_workspace import git, head


async def test_the_board_can_undo_only_an_identified_applied_run(tmp_path):
    import httpx

    from poieo.web.server import create_app

    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "pass"']})
    daemon, result = await run_once(config)
    url = f"/api/tasks/{config.display_name}/chores/undo"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(daemon)), base_url="http://localhost"
    ) as client:
        assert (await client.post(url, json={})).status_code == 400
        answer = await client.post(url, json={"run_id": result.run_id})
        assert answer.status_code == 200, answer.text
        assert answer.json()["undo_of"] == result.run_id
    assert not (repo / "made.txt").exists()


async def test_undo_preserves_later_work_and_records_a_new_change(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "pass"']})
    daemon, result = await run_once(config)
    (repo / "later.txt").write_text("someone else's work")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "later work")
    before_undo = head(repo, "HEAD")
    driver = daemon.runners[0]

    outcome = await driver.undo_changes(result.run_id)

    assert outcome["status"] == "applied"
    assert not (repo / "made.txt").exists()
    assert (repo / "later.txt").read_text() == "someone else's work"
    assert git(repo, "merge-base", "--is-ancestor", before_undo, "HEAD") == ""
    assert driver.holding
    assert daemon.store.summary(result.run_id)["application"]["status"] == "undone"
    undo = daemon.store.summary(outcome["run_id"])
    assert undo["change"]["base"] == before_undo
    assert undo["application"]["undo_of"] == result.run_id


async def test_undo_refuses_conflicts_with_later_work(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "pass"']})
    daemon, result = await run_once(config)
    (repo / "made.txt").write_text("newer work")
    git(repo, "commit", "-am", "newer work")
    before = head(repo, "HEAD")
    outcome = await daemon.runners[0].undo_changes(result.run_id)
    assert outcome["status"] == "blocked"
    assert outcome["conflict"] == ["made.txt"]
    assert head(repo, "HEAD") == before
    assert (repo / "made.txt").read_text() == "newer work"


async def test_undo_must_pass_the_current_checks(tmp_path):
    from test_task_application import CHECK_MADE

    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]})
    daemon, result = await run_once(config)
    before = head(repo, "HEAD")
    outcome = await daemon.runners[0].undo_changes(result.run_id)
    assert outcome["status"] == "blocked"
    assert outcome["checks"][0]["exit_code"] != 0
    assert head(repo, "HEAD") == before
    assert daemon.store.summary(result.run_id)["application"]["status"] == "applied"


async def test_a_previous_undo_cannot_remove_work_reintroduced_later(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "pass"']})
    daemon, result = await run_once(config)
    driver = daemon.runners[0]
    assert (await driver.undo_changes(result.run_id))["status"] == "applied"
    (repo / "made.txt").write_text("hi")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "intentionally reintroduce it")
    before = head(repo, "HEAD")
    again = await driver.undo_changes(result.run_id)
    assert again["status"] == "blocked"
    assert head(repo, "HEAD") == before
    assert (repo / "made.txt").read_text() == "hi"


async def test_undo_refuses_unsaved_user_edits_and_another_tasks_run(tmp_path):
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": ['python -c "pass"']})
    daemon, result = await run_once(config)
    (repo / "README.md").write_text("unsaved")
    driver = daemon.runners[0]
    assert (await driver.undo_changes(result.run_id))["dirty"] == ["README.md"]
    assert (repo / "README.md").read_text() == "unsaved"
    daemon.store.record_summary({**result.summary(), "task": "someone-else"})
    assert "another task" in (await driver.undo_changes(result.run_id))["error"]
