"""Overlapping work gets one bounded repair before it asks its owner."""

import asyncio

from test_task_application import CHECK_MADE, policy_config, run_once
from test_workspace import do_run, git, make_repo, workspace

from poieo.daemon.changes import check_and_apply
from poieo.workspace import ApplySpec


async def test_conflicting_work_is_repaired_privately_then_checked(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "README.md", "task addition\n")
    (repo / "README.md").write_text("other addition\n")
    git(repo, "commit", "-am", "another task")
    calls = []

    async def repair(prepared, failure, cancel):
        calls.append(failure)
        assert (repo / "README.md").read_text() == "other addition\n"
        (prepared.path / "README.md").write_text("other addition\ntask addition\n")
        point.save_repair(prepared, "repair1", "keep both additions")
        return {"ready": True, "run_id": "repair1"}

    result = await check_and_apply(
        point,
        ApplySpec(
            mode="auto",
            checks=["python -c \"from pathlib import Path; assert 'other addition' in Path('README.md').read_text()\""],
        ),
        repair=repair,
    )
    assert calls[0]["conflict"] == ["README.md"]
    assert result["status"] == "applied"
    assert result["repair"]["run_id"] == "repair1"
    assert (repo / "README.md").read_text() == "other addition\ntask addition\n"
    assert point.pending() == []


async def test_semantic_overlap_is_repaired_and_checked_again(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "old")
    calls = []

    async def repair(prepared, failure, cancel):
        calls.append(failure)
        (prepared.path / "made.txt").write_text("hi")
        point.save_repair(prepared, "repair1", "meet the check")
        return {"ready": True}

    result = await check_and_apply(point, ApplySpec(mode="auto", checks=[CHECK_MADE]), repair=repair)
    assert len(calls) == 1
    assert calls[0]["checks"][0]["exit_code"] == 1
    assert result["checks"][0]["exit_code"] == 0
    assert (repo / "made.txt").read_text() == "hi"


async def test_verification_artifacts_never_become_part_of_a_repair(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "old")

    async def repair(prepared, failure, cancel):
        (prepared.path / "made.txt").write_text("hi")
        point.save_repair(prepared, "repair1", "meet the check")
        return {"ready": True}

    command = (
        "python -c \"from pathlib import Path; Path('test-report.txt').write_text('report'); "
        "assert Path('made.txt').read_text() == 'hi'\""
    )
    result = await check_and_apply(point, ApplySpec(mode="auto", checks=[command]), repair=repair)
    assert result["status"] == "applied"
    assert (repo / "made.txt").read_text() == "hi"
    assert not (repo / "test-report.txt").exists()


async def test_failed_repair_is_not_repeated_or_applied(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "old")
    calls = []

    async def repair(prepared, failure, cancel):
        calls.append(failure)
        return {"ready": True}

    result = await check_and_apply(point, ApplySpec(mode="auto", checks=[CHECK_MADE]), repair=repair)
    assert result["status"] == "blocked"
    assert len(calls) == 1
    assert not (repo / "made.txt").exists()


async def test_repair_cannot_expand_the_allowed_scope(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "old")

    async def repair(prepared, failure, cancel):
        (prepared.path / "made.txt").write_text("hi")
        (prepared.path / "README.md").write_text("unauthorized")
        point.save_repair(prepared, "repair1", "too much")
        return {"ready": True}

    result = await check_and_apply(
        point, ApplySpec(mode="auto", paths=["made.txt"], checks=[CHECK_MADE]), repair=repair
    )
    assert result["outside_scope"] == ["README.md"]
    assert not (repo / "made.txt").exists()


async def test_revoked_permission_does_not_start_a_repair(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "old")

    async def repair(prepared, failure, cancel):
        raise AssertionError("permission was revoked")

    result = await check_and_apply(
        point, ApplySpec(mode="auto", checks=[CHECK_MADE]), repair=repair, authorized=lambda: False
    )
    assert result["status"] == "blocked"


async def test_a_task_repairs_failed_work_and_keeps_the_repair_run(tmp_path):
    responses = """          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: old}}
          - wrote made.txt
          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: hi}}
          - '{"decision":"ready","summary":"Updated made.txt to satisfy the check"}'
"""
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]}, responses=responses)
    daemon, result = await run_once(config)
    assert result.application["status"] == "applied"
    repaired = daemon.store.summary(result.application["repair"]["run_id"])
    assert repaired["task"] == result.task
    assert repaired["application"]["status"] == "applied"
    assert repaired["usage"]["input_tokens"] > 0
    assert repaired["change"]["head"] != result.change["head"]
    assert (repo / "made.txt").read_text() == "hi"
    assert not daemon.runners[0].holding


async def test_incompatible_goals_leave_the_original_unchanged_and_ask(tmp_path):
    responses = """          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: old}}
          - wrote made.txt
          - '{"decision":"needs_decision","summary":"The requested old value contradicts the check"}'
"""
    repo, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]}, responses=responses)
    daemon, result = await run_once(config)
    assert result.application["status"] == "blocked"
    assert result.application["repair"]["reason"] == "The requested old value contradicts the check"
    assert daemon.runners[0].holding
    assert not (repo / "made.txt").exists()


async def test_stopping_before_a_repair_keeps_it_from_starting(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "old")
    stopped = asyncio.Event()
    stopped.set()

    async def repair(prepared, failure, cancel):
        raise AssertionError("stopped work must not restart")

    result = await check_and_apply(point, ApplySpec(mode="auto", checks=[CHECK_MADE]), repair=repair, cancel=stopped)
    assert result["status"] == "blocked"
    assert not (repo / "made.txt").exists()


async def test_identical_work_is_reported_as_already_included(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "hi")
    (repo / "made.txt").write_text("hi")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "same work already done")
    result = await check_and_apply(point, ApplySpec(mode="auto", checks=[CHECK_MADE]))
    assert result["status"] == "applied"
    assert result["unchanged"] is True
    assert point.pending() == []


async def test_a_failed_check_cannot_smuggle_its_edits_into_a_repair(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "made.txt", "hi")

    async def repair(prepared, failure, cancel):
        raise AssertionError("a check must not edit the proposed change")

    result = await check_and_apply(
        point,
        ApplySpec(
            mode="auto",
            checks=[
                "python -c \"from pathlib import Path; Path('made.txt').write_text('changed'); raise SystemExit(1)\""
            ],
        ),
        repair=repair,
    )
    assert result["verification_changed"] == ["made.txt"]
    assert not (repo / "made.txt").exists()
