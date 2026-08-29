"""The git seam, against real repositories.

Every test builds an actual repository in tmp_path. Mocking git here would
test the mock: the whole point of this module is that git's real behaviour --
what a fast-forward refuses, what a conflict leaves behind -- is what the
daemon has to live with.
"""

import subprocess

import pytest

from poieo.workspace import Change, Workspace, WorkspaceError


def git(cwd, *args):
    result = subprocess.run(
        ["git", "-c", "user.name=tester", "-c", "user.email=tester@localhost", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result.stdout


def make_repo(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("hello", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "initial")
    return repo


def workspace(tmp_path, repo, task="chores"):
    return Workspace(repo, task, tmp_path / "store")


def head(repo, ref="HEAD"):
    return git(repo, "rev-parse", ref).strip()


def clean(repo):
    return git(repo, "status", "--porcelain", "--untracked-files=no").strip() == ""


def do_run(point, run_id, name, body, *, failed=False):
    """One task run: prepare, write something, commit."""
    point.prepare()
    (point.worktree / name).write_text(body, encoding="utf-8")
    return point.commit(run_id, f"wrote {name}", failed=failed)


def test_unavailable_outside_a_repo(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert Workspace(plain, "chores", tmp_path / "store").available() is False


def test_available_inside_a_repo(tmp_path):
    repo = make_repo(tmp_path)
    assert workspace(tmp_path, repo).available() is True


def test_prepare_creates_private_worktree(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)

    base = point.prepare()

    assert point.worktree.is_dir()
    assert (point.worktree / "README.md").read_text(encoding="utf-8") == "hello"
    assert git(point.worktree, "rev-parse", "--abbrev-ref", "HEAD").strip() == "poieo/chores"
    assert base == head(repo)
    # the user's own checkout is exactly where they left it
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert clean(repo)


def test_prepare_is_idempotent(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)

    first = point.prepare()
    (point.worktree / "marker.txt").write_text("still here", encoding="utf-8")
    second = point.prepare()

    assert second == first
    assert (point.worktree / "marker.txt").exists()


def test_prepare_repairs_a_deleted_worktree(tmp_path):
    import shutil

    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    point.prepare()

    shutil.rmtree(point.worktree)  # the directory is disposable
    point.prepare()

    assert (point.worktree / "README.md").exists()


def test_commit_records_the_change(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    before = head(repo, "main")

    change = do_run(point, "r1", "new.py", "print(1)")

    assert isinstance(change, Change)
    assert change.files == ["new.py"]
    assert change.message == "wrote new.py"
    assert change.insertions > 0
    assert change.base == before
    assert head(repo, "poieo/chores") == change.head
    # the user's checkout never learned about any of it
    assert head(repo, "main") == before
    assert not (repo / "new.py").exists()
    assert clean(repo)


def test_commit_returns_none_when_nothing_changed(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    point.prepare()
    before = head(repo, "poieo/chores")

    assert point.commit("r1", "did nothing") is None
    assert head(repo, "poieo/chores") == before


def test_failed_run_stays_off_the_branch(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    point.prepare()
    before = head(repo, "poieo/chores")

    change = do_run(point, "r-bad", "half.py", "print(", failed=True)

    assert head(repo, "poieo/chores") == before
    # the work is parked, not lost
    assert head(repo, "refs/poieo/failed/r-bad") == change.head
    assert point.pending() == []


def test_prepare_fast_forwards_to_user_branch(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    point.prepare()

    (repo / "README.md").write_text("hello again", encoding="utf-8")
    git(repo, "commit", "-am", "user moved on")
    moved = head(repo, "main")

    base = point.prepare()

    assert base == moved
    assert head(repo, "poieo/chores") == moved
    assert (point.worktree / "README.md").read_text(encoding="utf-8") == "hello again"


def test_prepare_leaves_pending_work_alone(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    change = do_run(point, "r1", "new.py", "print(1)")

    (repo / "README.md").write_text("hello again", encoding="utf-8")
    git(repo, "commit", "-am", "user moved on")

    base = point.prepare()

    # unreviewed work is not rebased out from under the reader
    assert head(repo, "poieo/chores") == change.head
    assert base == change.head


def test_accept_fast_forwards_user_branch(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "one.py", "print(1)")
    second = do_run(point, "r2", "two.py", "print(2)")

    assert point.accept(None) == {"accepted": 2}

    assert head(repo, "main") == second.head
    assert (repo / "one.py").exists() and (repo / "two.py").exists()
    # the private copy is still usable afterwards
    assert point.prepare() == head(repo, "main")


def test_accept_through_a_run_is_linear(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    first = do_run(point, "r1", "one.py", "print(1)")
    do_run(point, "r2", "two.py", "print(2)")

    assert point.accept(first.head) == {"accepted": 1}

    assert head(repo, "main") == first.head
    assert not (repo / "two.py").exists()
    assert len(point.pending()) == 1


def test_accept_refuses_a_dirty_checkout(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "one.py", "print(1)")
    before = head(repo, "main")

    (repo / "README.md").write_text("uncommitted edit", encoding="utf-8")

    assert point.accept(None) == {"dirty": ["README.md"]}
    assert head(repo, "main") == before


def test_accept_reports_conflict_without_merging(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "README.md", "written by the task")

    (repo / "README.md").write_text("written by the user", encoding="utf-8")
    git(repo, "commit", "-am", "user edit")
    before = head(repo, "main")

    assert point.accept(None) == {"conflict": ["README.md"]}

    assert head(repo, "main") == before
    # nothing half-merged left behind for the user to discover
    assert clean(repo)
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_discard_moves_the_branch_back_and_parks_it(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    do_run(point, "r1", "one.py", "print(1)")
    last = do_run(point, "r2", "two.py", "print(2)")

    assert point.discard(None) == {"discarded": 2}

    assert head(repo, "poieo/chores") == head(repo, "main")
    assert point.pending() == []
    # discarding is recoverable
    assert head(repo, "refs/poieo/discarded/r2") == last.head
    assert not (point.worktree / "two.py").exists()


def test_discard_from_a_run_keeps_the_earlier_one(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    first = do_run(point, "r1", "one.py", "print(1)")
    second = do_run(point, "r2", "two.py", "print(2)")

    assert point.discard(second.head) == {"discarded": 1}

    assert head(repo, "poieo/chores") == first.head
    assert (point.worktree / "one.py").exists()


def test_diff_reports_files_and_truncates(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    change = do_run(point, "r1", "new.py", "one" + chr(10) + "two" + chr(10))

    report = point.diff(change.base, change.head)

    assert report["files"] == [{"path": "new.py", "status": "A", "insertions": 2, "deletions": 0}]
    assert "new.py" in report["patch"]
    assert report["truncated"] is False

    clipped = point.diff(change.base, change.head, max_bytes=20)
    assert clipped["truncated"] is True
    assert len(clipped["patch"]) <= 20
    assert clipped["files"] == report["files"]  # the list survives truncation


def test_diff_survives_a_binary_file(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)
    point.prepare()
    (point.worktree / "blob.bin").write_bytes(bytes(range(256)))
    change = point.commit("r1", "added a blob")

    report = point.diff(change.base, change.head)

    # --numstat reports "-" for binary; that must not crash the parser
    assert report["files"][0]["path"] == "blob.bin"
    assert report["files"][0]["insertions"] == 0


def test_a_broken_repository_raises_rather_than_corrupts(tmp_path):
    repo = make_repo(tmp_path)
    point = workspace(tmp_path, repo)

    with pytest.raises(WorkspaceError):
        point.diff("deadbeef", "cafebabe")
