"""A change is checked against the current project before it reaches the user."""

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from test_workspace import clean, do_run, git, head, make_repo, workspace

from poieo.workspace import Workspace


def test_preparing_a_combined_change_leaves_both_originals_untouched(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    change = do_run(point, "r1", "task.txt", "from the task")
    (repo / "user.txt").write_text("from the user", encoding="utf-8")
    git(repo, "add", "user.txt")
    git(repo, "commit", "-m", "user moved on")
    before = head(repo, "HEAD")

    prepared = point.prepare_accept()
    try:
        assert (prepared.path / "task.txt").read_text() == "from the task"
        assert (prepared.path / "user.txt").read_text() == "from the user"
        assert head(repo, "HEAD") == before
        assert head(repo, point.branch) == change.head
        assert not (repo / "task.txt").exists()
        assert point.apply_prepared(prepared) == {"accepted": 1, "before": before, "after": prepared.head}
        assert (repo / "task.txt").exists() and (repo / "user.txt").exists()
        assert clean(repo)
    finally:
        point.release_prepared(prepared)
    assert not prepared.path.exists()


def test_a_conflict_is_kept_in_the_private_candidate(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    change = do_run(point, "r1", "README.md", "task version\n")
    (repo / "README.md").write_text("user version\n", encoding="utf-8")
    git(repo, "commit", "-am", "user edit")
    before = head(repo, "HEAD")

    prepared = point.prepare_accept()
    try:
        assert prepared.conflict == ["README.md"]
        assert "<<<<<<<" in (prepared.path / "README.md").read_text()
        assert point.apply_prepared(prepared) == {"conflict": ["README.md"]}
        assert head(repo, "HEAD") == before
        assert head(repo, point.branch) == change.head
        assert clean(repo)
    finally:
        point.release_prepared(prepared)


def test_a_changed_project_must_be_checked_again(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "task.txt", "work")
    prepared = point.prepare_accept()
    try:
        (repo / "user.txt").write_text("newer work", encoding="utf-8")
        git(repo, "add", "user.txt")
        git(repo, "commit", "-m", "later user edit")
        assert point.apply_prepared(prepared) == {"stale": "the project changed during verification"}
        assert not (repo / "task.txt").exists()
        assert (repo / "user.txt").read_text() == "newer work"
    finally:
        point.release_prepared(prepared)


def test_switching_branches_at_the_same_commit_invalidates_verification(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "task.txt", "work")
    prepared = point.prepare_accept()
    try:
        git(repo, "switch", "-c", "another")
        assert "stale" in point.apply_prepared(prepared)
        assert not (repo / "task.txt").exists()
    finally:
        point.release_prepared(prepared)


def test_verification_cannot_silently_rewrite_the_candidate(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "task.txt", "work")
    prepared = point.prepare_accept()
    try:
        (prepared.path / "task.txt").write_text("changed by the check", encoding="utf-8")
        assert point.apply_prepared(prepared) == {"verification_changed": ["task.txt"]}
        assert not (repo / "task.txt").exists()
    finally:
        point.release_prepared(prepared)


def test_discarding_work_invalidates_an_earlier_verification(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "task.txt", "work")
    prepared = point.prepare_accept()
    try:
        point.discard()
        assert "stale" in point.apply_prepared(prepared)
        assert not (repo / "task.txt").exists()
    finally:
        point.release_prepared(prepared)


def test_a_run_from_another_task_cannot_be_accepted(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    point.prepare()
    other = Workspace(repo, "other", tmp_path / "worktrees")
    change = do_run(other, "other-run", "other.txt", "another task")

    assert point.accept(change.head) == {"stale": "this change no longer belongs to the task"}
    assert not (repo / "other.txt").exists()


def test_competing_acceptances_never_overwrite_one_another(tmp_path):
    repo = make_repo(tmp_path)
    first = workspace(tmp_path, repo)
    second = Workspace(repo, "second", tmp_path / "worktrees")
    do_run(first, "r1", "one.txt", "one")
    do_run(second, "r2", "two.txt", "two")
    candidates = [first.prepare_accept(), second.prepare_accept()]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda pair: pair[0].apply_prepared(pair[1]), zip((first, second), candidates)))
        assert sum("accepted" in outcome for outcome in outcomes) == 1
        assert sum("stale" in outcome for outcome in outcomes) == 1
        assert clean(repo)
        waiting = second if "stale" in outcomes[1] else first
        assert waiting.accept() == {"accepted": 1}
        assert (repo / "one.txt").exists() and (repo / "two.txt").exists()
    finally:
        for point, prepared in zip((first, second), candidates):
            point.release_prepared(prepared)


def test_user_edits_made_during_verification_are_preserved(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "task.txt", "work")
    prepared = point.prepare_accept()
    try:
        (repo / "README.md").write_text("unsaved user work", encoding="utf-8")
        assert point.apply_prepared(prepared) == {"dirty": ["README.md"]}
        assert (repo / "README.md").read_text() == "unsaved user work"
        assert not (repo / "task.txt").exists()
    finally:
        point.release_prepared(prepared)


def test_another_process_can_finish_a_slow_application(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "task.txt", "work")
    ready, release = tmp_path / "ready", tmp_path / "release"
    script = """
import sys, time
from pathlib import Path
from poieo.workspace import _repository_lock
with _repository_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).touch()
    while not Path(sys.argv[3]).exists():
        time.sleep(0.02)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(repo), str(ready), str(release)],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    timer = None
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        # Windows' LK_LOCK stops retrying after about nine seconds. A real
        # independent owner held beyond that point must still hand over safely.
        timer = threading.Timer(10.2, release.touch)
        timer.start()
        assert point.accept() == {"accepted": 1}
        assert (repo / "task.txt").read_text() == "work"
    finally:
        release.touch()
        if timer is not None:
            timer.cancel()
        process.wait(timeout=10)
