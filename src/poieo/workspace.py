"""The only module in poieo that knows git exists.

A task with a workdir works in a private copy -- a linked worktree on a branch
of its own -- so a night of runs never touches what the user left open, and
each run lands as one change to read, take, or throw away in the morning.

**Everything here is synchronous, and every caller wraps it in
``asyncio.to_thread``**: a blocking subprocess on the loop the daemon shares
with the web server would stall the event stream for every watcher.

Design: docs/workspace.md
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Iterator, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import PoieoError

# Automated commits must work on a machine with no global git identity.
_IDENTITY = ["-c", "user.name=poieo", "-c", "user.email=poieo@localhost"]


class WorkspaceError(PoieoError):
    """A git operation failed. Never fatal to a task -- the work still ran."""


class ApplySpec(BaseModel):
    """The user's permission to apply a task's verified file changes."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["review", "auto"] = "review"
    paths: list[str] = Field(default_factory=list, max_length=50)
    checks: list[str] = Field(default_factory=list, max_length=10)
    timeout: float = Field(default=120, gt=0, le=600)

    @field_validator("paths")
    @classmethod
    def _paths(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            value = value.strip().replace("\\", "/")
            path = PurePosixPath(value)
            if (
                not value
                or path.is_absolute()
                or PureWindowsPath(value).drive
                or ".." in path.parts
                or any(part.lower() == ".git" for part in path.parts)
                or any(char in value for char in "*?[]\0")
            ):
                raise ValueError("an allowed path must name a file or folder inside the task folder")
            normalized.append(path.as_posix())
        return list(dict.fromkeys(normalized))

    @field_validator("checks")
    @classmethod
    def _checks(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 4000 for value in values):
            raise ValueError("each verification command must contain 1 to 4000 characters")
        return [value.strip() for value in values]

    @model_validator(mode="after")
    def _automatic_needs_checks(self) -> ApplySpec:
        if self.mode == "auto" and not self.checks:
            raise ValueError("automatic application needs at least one verification command")
        return self


@dataclass(slots=True)
class Change:
    """What one run did, as two commit ids and a tally."""

    base: str
    head: str
    files: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    # The run's own one-line account of itself, which is what a reader sees
    # first. It lives in the commit too, but nothing downstream reads that.
    message: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "base": self.base,
            "head": self.head,
            "files": list(self.files),
            "insertions": self.insertions,
            "deletions": self.deletions,
            "message": self.message,
        }


@dataclass(slots=True)
class PreparedChange:
    """A disposable combined result, tied to the project version it was checked on."""

    path: Path
    base: str
    branch: str
    target: str
    head: str
    count: int
    conflict: list[str] = field(default_factory=list)


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def _repository_lock(repo: Path, *, task: str | None = None) -> Iterator[None]:
    """Serialize poieo's writes across tasks, threads, and daemon processes."""
    common = Path(_git(repo, "rev-parse", "--git-common-dir").strip())
    common = (repo / common).resolve() if not common.is_absolute() else common.resolve()
    name = "poieo-accept.lock" if task is None else f"poieo-task-{hashlib.sha256(task.encode()).hexdigest()}.lock"
    key = os.path.normcase(str(common / name))
    busy = (
        "another poieo process is still applying a change; try again"
        if task is None
        else "this task is already running in another process"
    )
    with _LOCKS_GUARD:
        local = _LOCKS.setdefault(key, threading.Lock())
    if not local.acquire(timeout=60 if task is None else 0):
        raise WorkspaceError(busy)
    try:
        with _locked_file(common / name, wait=60 if task is None else 0, busy=busy):
            yield
    finally:
        local.release()


@contextmanager
def _locked_file(path: Path, *, wait: float, busy: str) -> Iterator[None]:
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + wait
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise WorkspaceError(f"could not coordinate changes: {exc}") from exc
                if time.monotonic() >= deadline:
                    raise WorkspaceError(busy) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *_IDENTITY, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:  # git missing from PATH, cwd gone
        raise WorkspaceError(str(exc)) from exc
    if result.returncode != 0:
        raise WorkspaceError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


def _numstat_rows(raw: str) -> Iterator[tuple[str, int, int]]:
    """``git diff --numstat`` as ``(path, insertions, deletions)`` per file.

    Binary files report ``-`` for both counts and are reported with zeroes
    rather than skipped -- they still changed. A rename reads
    ``R100<tab>old<tab>new``, so the last field is the path worth naming.
    """
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, removed = parts[0], parts[1]
        yield (
            parts[-1],
            int(added) if added.isdigit() else 0,
            int(removed) if removed.isdigit() else 0,
        )


def _parse_numstat(raw: str) -> tuple[list[str], int, int]:
    files: list[str] = []
    insertions = deletions = 0
    for path, added, removed in _numstat_rows(raw):
        files.append(path)
        insertions += added
        deletions += removed
    return files, insertions, deletions


def usable(folder: Path) -> bool:
    """Whether git could keep a private copy of ``folder``.

    git on PATH, and the folder actually inside a work tree. A free function
    and not only a method, because the question is asked about folders no task
    owns: the board asks it of a project so the make panel can say, before a
    task exists, whether the night it starts could be thrown away.

    Anything git could not answer is False. A folder nobody can prove is
    protected is one somebody should look at.
    """
    if shutil.which("git") is None:
        return False
    try:
        return _git(folder, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except WorkspaceError:
        return False


class Workspace:
    """A task's private copy of one repository, and the change it is building."""

    def __init__(self, repo: Path, task: str, worktrees: Path):
        self.repo = Path(repo)
        self.task = task
        # The folder that holds every task's copy, not the project root: this
        # used to be handed the run-log store and append `worktrees` itself,
        # which meant pointing the logs at another disk quietly took the
        # working copies along. A copy of a repository is not a log.
        self.worktrees = Path(worktrees).resolve()

    @property
    def branch(self) -> str:
        return f"poieo/{self.task}"

    @property
    def worktree(self) -> Path:
        return self.worktrees / self.task

    # -- inspection ---------------------------------------------------------

    @contextmanager
    def exclusive_run(self) -> Iterator[None]:
        """Keep another runner from resetting or committing this task's copy."""
        if not self.available():
            yield
            return
        with _repository_lock(self.repo, task=self.task):
            yield

    def applied(self, commit: str) -> bool:
        return self._is_ancestor(commit, "HEAD")

    def run_ids(self, commits: Sequence[str]) -> list[str]:
        wanted = set(commits)
        refs = _git(self.repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/poieo/runs")
        return [
            ref.rsplit("/", 1)[-1]
            for line in refs.splitlines()
            for commit, ref in [line.split(" ", 1)]
            if commit in wanted
        ]

    def available(self) -> bool:
        """git on PATH, and the workdir actually inside a repository."""
        return usable(self.repo)

    def into(self) -> str:
        """What accepting would add to -- the branch the user is standing on."""
        return _git(self.repo, "rev-parse", "--abbrev-ref", "HEAD").strip()

    def pending(self) -> list[str]:
        """Commits on the task's branch that the user's HEAD does not contain."""
        if not self._branch_exists():
            return []
        return _git(self.repo, "rev-list", f"HEAD..{self.branch}").split()

    def diff(self, base: str, head: str, *, max_bytes: int = 400_000) -> dict[str, object]:
        numstat = _git(self.repo, "diff", "--numstat", base, head)
        statuses: dict[str, str] = {}
        for line in _git(self.repo, "diff", "--name-status", base, head).splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                # A rename reads "R100<tab>old<tab>new"; the last field is where
                # the change lands, which is the path worth reporting.
                statuses[parts[-1]] = parts[0][:1]

        files = [
            {
                "path": path,
                "status": statuses.get(path, "M"),
                "insertions": added,
                "deletions": removed,
            }
            for path, added, removed in _numstat_rows(numstat)
        ]

        patch = _git(self.repo, "diff", base, head)
        truncated = len(patch) > max_bytes
        return {
            "base": base,
            "head": head,
            "files": files,
            "patch": patch[:max_bytes] if truncated else patch,
            "truncated": truncated,
        }

    # -- the run boundary ---------------------------------------------------

    def prepare(self) -> str:
        """Make the private copy ready to work in; return the commit it starts from."""
        user_head = _git(self.repo, "rev-parse", "HEAD").strip()
        if not self._branch_exists():
            _git(self.repo, "branch", self.branch, user_head)
        self._ensure_worktree()

        self.working_folder()

        # Follow the user forward only while there is nothing to review:
        # rebasing unread work out from under them would lose it.
        if not self.pending():
            _git(self.worktree, "reset", "--hard", user_head)
            return user_head
        return _git(self.repo, "rev-parse", self.branch).strip()

    def commit(self, run_id: str, message: str, *, failed: bool = False) -> Change | None:
        """Land the run's work. None when it changed nothing -- not a failure."""
        work = self.worktree
        _git(work, "add", "-A")
        if not _git(work, "diff", "--cached", "--name-only").strip():
            return None

        base = _git(work, "rev-parse", "HEAD").strip()
        _git(work, "commit", "-m", message)
        head = _git(work, "rev-parse", "HEAD").strip()

        # Every run stays reachable by its own id, accepted or not.
        _git(self.repo, "update-ref", f"refs/poieo/runs/{run_id}", head)
        if failed:
            _git(self.repo, "update-ref", f"refs/poieo/failed/{run_id}", head)
            _git(work, "reset", "--hard", base)

        files, insertions, deletions = _parse_numstat(_git(self.repo, "diff", "--numstat", base, head))
        return Change(
            base=base,
            head=head,
            files=files,
            insertions=insertions,
            deletions=deletions,
            message=message.splitlines()[0] if message else "",
        )

    def park_failed(self, change: Change, run_id: str) -> None:
        """Retain a cancelled save without offering it to a later successful run."""
        if _git(self.worktree, "rev-parse", "HEAD").strip() != change.head:
            raise WorkspaceError("the task changed before its cancelled work could be parked")
        _git(self.repo, "update-ref", f"refs/poieo/failed/{run_id}", change.head)
        _git(self.worktree, "reset", "--hard", change.base)

    # -- the morning after --------------------------------------------------

    def accept(self, through: str | None = None) -> dict[str, object]:
        """Combine privately, then apply without leaving a merge in the user's files."""
        prepared = self.prepare_accept(through)
        if isinstance(prepared, dict):
            return prepared
        try:
            outcome = self.apply_prepared(prepared)
            # Keep the original manual-review response; automated callers also
            # retain before/after so the exact accepted work stays inspectable.
            return {"accepted": outcome["accepted"]} if "accepted" in outcome else outcome
        finally:
            self.release_prepared(prepared)

    def prepare_accept(self, through: str | None = None) -> PreparedChange | dict[str, object]:
        """Combine a task and the current project in a separate, disposable copy."""
        with _repository_lock(self.repo):
            dirty = self._dirty()
            if dirty:
                return {"dirty": dirty}
            target = through or _git(self.repo, "rev-parse", self.branch).strip()
            if not self._is_ancestor(target, self.branch):
                return {"stale": "this change no longer belongs to the task"}
            base = _git(self.repo, "rev-parse", "HEAD").strip()
            count = len(_git(self.repo, "rev-list", f"{base}..{target}").split())
            if count == 0:
                return {"accepted": 0}
            branch = _git(self.repo, "rev-parse", "--symbolic-full-name", "HEAD").strip()
            self.worktrees.mkdir(parents=True, exist_ok=True)
            path = Path(tempfile.mkdtemp(prefix=".review-", dir=self.worktrees)).resolve()
            prepared = PreparedChange(path, base, branch, target, target, count)
            # Fast-forward candidates retain the run's identity. Divergent work
            # is combined here, never provisionally in the user's checkout.
            straight = self._is_ancestor(base, target)
            try:
                _git(self.repo, "worktree", "add", "--detach", str(path), target if straight else base)
                if not straight:
                    try:
                        _git(path, "merge", "--no-commit", "--no-ff", target)
                    except WorkspaceError:
                        prepared.conflict = self._conflicts(path)
                        if not prepared.conflict:
                            raise
                        prepared.head = base
                        return prepared
                    _git(path, "commit", "-m", f"poieo: accept {self.task}")
                    prepared.head = _git(path, "rev-parse", "HEAD").strip()
                return prepared
            except BaseException:
                if (path / ".git").exists():
                    _git(self.repo, "worktree", "remove", "--force", str(path))
                else:
                    path.rmdir()
                raise

    def apply_prepared(
        self, prepared: PreparedChange, *, permitted: Callable[[], bool] | None = None
    ) -> dict[str, object]:
        """Apply exactly the checked result, provided neither side changed meanwhile."""
        with _repository_lock(self.repo):
            if prepared.conflict:
                return {"conflict": list(prepared.conflict)}
            dirty = self._dirty()
            if dirty:
                return {"dirty": dirty}
            if (
                _git(self.repo, "rev-parse", "HEAD").strip() != prepared.base
                or _git(self.repo, "rev-parse", "--symbolic-full-name", "HEAD").strip() != prepared.branch
            ):
                return {"stale": "the project changed during verification"}
            if not self._is_ancestor(prepared.target, self.branch):
                return {"stale": "this change no longer belongs to the task"}
            invalid = self.validate_prepared(prepared)
            if invalid:
                return invalid
            if permitted is not None and not permitted():
                return {"revoked": True}
            _git(self.repo, "merge", "--ff-only", prepared.head)
            unchanged = not _git(self.repo, "diff", "--name-only", prepared.base, prepared.head).strip()
            return {
                "accepted": prepared.count,
                "before": prepared.base,
                "after": prepared.head,
                **({"unchanged": True} if unchanged else {}),
            }

    def save_repair(self, prepared: PreparedChange, run_id: str, message: str) -> Change | None:
        """Keep a repaired combination on the task's copy for verification or review."""
        if _git(prepared.path, "rev-parse", "HEAD").strip() != prepared.head:
            raise WorkspaceError("the repair changed its history unexpectedly")
        for name in prepared.conflict:
            path = prepared.path / name
            if path.is_file() and any(
                line.startswith((b"<<<<<<< ", b"=======", b">>>>>>> ")) for line in path.read_bytes().splitlines()
            ):
                raise WorkspaceError("the repair left unresolved conflict markers")
        base = prepared.head
        _git(prepared.path, "add", "-A")
        if not prepared.conflict and not _git(prepared.path, "diff", "--cached", "--name-only").strip():
            return None
        _git(prepared.path, "commit", "-m", message)
        head = _git(prepared.path, "rev-parse", "HEAD").strip()
        if not self._is_ancestor(prepared.base, head) or not self._is_ancestor(prepared.target, head):
            raise WorkspaceError("the repair lost work from the project or task")
        _git(self.repo, "update-ref", f"refs/poieo/runs/{run_id}", head)
        # This copy stays inspectable even when the next check fails. It also
        # becomes the source of a fresh combination if the project moves again.
        _git(self.worktree, "merge", "--ff-only", head)
        prepared.head = prepared.target = head
        prepared.conflict = []
        prepared.count = len(_git(self.repo, "rev-list", f"{prepared.base}..{head}").split())
        files, insertions, deletions = _parse_numstat(_git(self.repo, "diff", "--numstat", base, head))
        return Change(base, head, files, insertions, deletions, message)

    def validate_prepared(self, prepared: PreparedChange) -> dict[str, object]:
        """A check is valid only for the unchanged candidate it was given."""
        changed = self._dirty_at(prepared.path)
        if changed:
            return {"verification_changed": changed}
        if _git(prepared.path, "rev-parse", "HEAD").strip() != prepared.head:
            return {"stale": "the change changed during verification"}
        return {}

    def release_prepared(self, prepared: PreparedChange) -> None:
        """Remove only the temporary copy this acceptance owns."""
        path = prepared.path.resolve()
        if path.parent != self.worktrees.resolve() or not path.name.startswith(".review-"):
            raise WorkspaceError("the temporary change is outside this task's work copies")
        with _repository_lock(self.repo):
            _git(self.repo, "worktree", "remove", "--force", str(path))

    def working_folder(self) -> Path:
        """The chosen task folder in its private copy, including a subfolder."""
        return self._folder_in(self.worktree)

    def check_folder(self, prepared: PreparedChange) -> Path:
        """The task's chosen folder inside the combined copy."""
        return self._folder_in(prepared.path)

    def _folder_in(self, copy: Path) -> Path:
        self._check_copy_root(copy)
        root = Path(_git(self.repo, "rev-parse", "--show-toplevel").strip()).resolve()
        folder = copy / self.repo.resolve().relative_to(root)
        if not folder.resolve().is_relative_to(copy.resolve()):
            raise WorkspaceError("the task folder moved outside its private copy")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError(f"the task folder could not be opened: {exc}") from exc
        return folder

    def outside_scope(self, prepared: PreparedChange, paths: list[str], protected: Sequence[Path] = ()) -> list[str]:
        """Changed paths outside the user's grant, including both sides of a rename."""
        root = Path(_git(self.repo, "rev-parse", "--show-toplevel").strip()).resolve()
        relative = self.repo.resolve().relative_to(root)

        def normalized(path: str) -> str:
            return os.path.normcase(path).replace("\\", "/").rstrip("/")

        allowed = [normalized((relative / path).as_posix()) for path in paths or ["."]]
        reserved = {
            normalized(path.resolve().relative_to(root).as_posix())
            for path in protected
            if path.resolve().is_relative_to(root)
        }
        changed = filter(
            None,
            _git(
                prepared.path,
                "diff",
                "--name-only",
                "--no-renames",
                "-z",
                prepared.base,
                *([] if prepared.conflict else [prepared.head]),
            ).split("\0"),
        )
        return [
            name
            for name in changed
            if any(normalized(name) == kept or normalized(name).startswith(kept + "/") for kept in reserved)
            or not any(
                prefix == "." or normalized(name) == prefix or normalized(name).startswith(prefix + "/")
                for prefix in allowed
            )
        ]

    def discard(self, since: str | None = None) -> dict[str, object]:
        """Throw the work away -- recoverably. The old tip stays on a parked ref."""
        with _repository_lock(self.repo):
            return self._discard(since)

    def _discard(self, since: str | None) -> dict[str, object]:
        if not self._branch_exists():
            return {"discarded": 0}

        old_tip = _git(self.repo, "rev-parse", self.branch).strip()
        back_to = (
            _git(self.repo, "rev-parse", f"{since}^").strip() if since else _git(self.repo, "rev-parse", "HEAD").strip()
        )
        dropped = _git(self.repo, "rev-list", f"{back_to}..{old_tip}").split()
        if not dropped:
            return {"discarded": 0}

        _git(self.repo, "update-ref", f"refs/poieo/discarded/{self._run_id_for(old_tip)}", old_tip)
        self._ensure_worktree()
        _git(self.worktree, "reset", "--hard", back_to)
        return {"discarded": len(dropped)}

    # -- plumbing -----------------------------------------------------------

    def _branch_exists(self) -> bool:
        try:
            _git(self.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{self.branch}")
            return True
        except WorkspaceError:
            return False

    def _is_ancestor(self, older: str, newer: str) -> bool:
        try:
            _git(self.repo, "merge-base", "--is-ancestor", older, newer)
            return True
        except WorkspaceError:
            return False

    def _dirty(self) -> list[str]:
        # Tracked changes only: the store often lives inside the project, and an
        # untracked directory is not a reason to refuse the user's own work.
        return self._dirty_at(self.repo)

    @staticmethod
    def _dirty_at(path: Path) -> list[str]:
        raw = _git(path, "status", "--porcelain", "-z", "--untracked-files=no")
        records = iter(raw.split("\0"))
        paths = []
        for record in records:
            if not record:
                continue
            paths.append(record[3:])
            if "R" in record[:2] or "C" in record[:2]:
                paths.append(next(records))
        return sorted(set(paths))

    @staticmethod
    def _conflicts(path: Path) -> list[str]:
        return list(filter(None, _git(path, "diff", "--name-only", "--diff-filter=U", "-z").split("\0")))

    def _run_id_for(self, commit: str) -> str:
        """Which run produced this commit, so discarded work is findable by name."""
        raw = _git(self.repo, "for-each-ref", "--format=%(objectname) %(refname)", "refs/poieo/runs")
        for line in raw.splitlines():
            objectname, _, refname = line.partition(" ")
            if objectname == commit:
                return refname.rsplit("/", 1)[-1]
        return commit[:12]

    def _ensure_worktree(self) -> None:
        work = self.worktree
        self._check_copy_root(work)
        if (work / ".git").exists():
            if not (work / ".git").is_file() or _git(work, "symbolic-ref", "--short", "HEAD").strip() != self.branch:
                raise WorkspaceError("the private copy no longer belongs to this task")
            return

        # The directory is disposable: a half-registered worktree (the user
        # deleted it, or .git/worktrees went missing) is repaired by throwing
        # the directory away and asking git for a fresh one.
        _git(self.repo, "worktree", "prune")
        if work.exists():
            shutil.rmtree(work)
        work.parent.mkdir(parents=True, exist_ok=True)
        _git(self.repo, "worktree", "add", work.as_posix(), self.branch)

    @staticmethod
    def _check_copy_root(copy: Path) -> None:
        if copy.resolve() != copy.absolute():
            raise WorkspaceError("the private copy was redirected outside its owned folder")
