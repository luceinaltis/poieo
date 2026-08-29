"""The resident process: keeps tasks firing until it is told to stop."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import socket
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Sequence

from ..workspace import Workspace, WorkspaceError
from ..errors import ExpressionError, PoieoError, SpecError
from ..expr import evaluate, wrap
from ..graph import Branch
from ..learn import learn as learn_pass
from ..memory import keeps_memory
from ..providers import ProviderPool
from ..runtime.context import RunResult, new_run_id
from ..runtime.executor import execute
from ..store import Event, RunStore
from ..card import append_journal, closing_line, record_run
from ..tools import ToolContext, make_container_pool, sweep_containers
from ..web import BroadcastStore, MergedStore, create_app
from .config import DaemonConfig, LoadedTask, load_tasks
from .triggers import Firing, _sleep_or_cancel, parse_duration

log = logging.getLogger("poieo.daemon")

RunCallback = Callable[[str, RunResult], None]


def _ensure_port_free(host: str, port: int) -> None:
    """Fail at launch, not after tasks have started."""
    with socket.socket() as sock:
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise SpecError(
                f"web port {port} is already in use on {host}: {exc}"
            ) from exc


SHUTDOWN_GRACE = 5.0


async def _stopped(task: "asyncio.Task[Any]", what: str) -> None:
    """Wait out one background task on the way down, and say what it did.

    Nothing here may keep the daemon from finishing -- the pools and the containers
    still have to be closed below -- so every outcome is logged, not raised.
    """
    try:
        await asyncio.wait_for(task, timeout=SHUTDOWN_GRACE)
    except asyncio.TimeoutError:
        log.warning("the %s did not stop within %gs; leaving it", what, SHUTDOWN_GRACE)
    except Exception as exc:
        log.warning("the %s stopped badly: %s", what, exc)


def _change_message(result: RunResult, task: str) -> str:
    """The model's own summary, shaped for a commit subject.

    The same reading the journal and the run record use.
    """
    said = closing_line(result, fallback="")
    if not said:
        return f"poieo {task} {result.run_id}"
    return said.strip().splitlines()[0][:72]


# Consecutive identical failures before a task holds itself. Staying up while
# failing identically is noise, not resilience.
PAUSE_AFTER = 3

# How many finished runs a runner keeps in memory. A RunResult carries the
# run's whole outputs and state, and only the tail is ever read; a loop task
# would otherwise accumulate every output for the daemon's lifetime.
RESULTS_KEPT = 20

# How far one chain of handoffs may reach -- `max_steps` one level up.
MAX_CHAIN = 10


def handoff_scope(result: RunResult) -> dict[str, Any]:
    """What a `then:` branch may test, and what the next run reads as `sender`.

    One shape, not two, so there is no second list to keep in sync -- and the
    same names a router reads inside a run, so a guard on what it spent is
    written once and moves between the two levels unchanged.

    ``change`` is present and None when a run altered nothing -- unlike
    :meth:`RunResult.summary`, which drops the key -- because
    ``when: "run.change"`` has to read false rather than raise.
    """
    return {
        "run_id": result.run_id,
        "task": result.task,
        "graph": result.graph,
        "status": result.status,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "steps": result.steps,
        "iteration": result.iteration,
        "path": list(result.path),
        "outputs": result.outputs,
        "state": result.state,
        "error": result.error,
        "cause": result.cause,
        "change": result.change,
        # What the run cost. A chain is bounded at MAX_CHAIN hops, which says
        # nothing about what those hops spend, so a card that wants to stop
        # handing work on before the bill grows has to be able to read it.
        "usage": result.usage,
        # What a person answered, when the run ended by asking one. None on
        # every other run, so `when: "run.answer == 'land'"` reads false
        # rather than raising on the runs that never asked.
        "answer": result.answer,
    }


@dataclass(slots=True)
class Handoff:
    """One task's finished run, offered to the task it named.

    Carries the depth so a chain can be bounded without any task having to know
    how it was reached, and the reason so the next run can record what fired it
    rather than the schedule it did not use.
    """

    result: dict[str, Any]
    reason: str
    depth: int


class TaskRunner:
    """Drives one task: trigger -> run -> carry state -> repeat."""

    def __init__(
        self,
        task: LoadedTask,
        config: DaemonConfig,
        pool: ProviderPool,
        store: RunStore,
        cancel: asyncio.Event,
        on_run: RunCallback | None = None,
        tool_context: ToolContext | None = None,
        handoff: Callable[["TaskRunner", RunResult, int], None] | None = None,
    ):
        self.task = task
        self.config = config
        self.pool = pool
        self.store = store
        self.cancel = cancel
        self.on_run = on_run
        self.trigger = task.spec.trigger.build()
        self.results: deque[RunResult] = deque(maxlen=RESULTS_KEPT)
        # Ending state of the last run, replayed into the next when carrying.
        self.state: dict[str, Any] = {}
        self.status: str = "waiting"
        # Consecutive failures sharing one cause; a completed run resets it.
        self._repeat_key: str | None = None
        self._repeat_count: int = 0
        self.current_run_id: str | None = None
        # The control seam: the board's three verbs poke these and the run loop
        # reads them between runs. The web server shares this event loop, so
        # flags and an Event are the whole mechanism.
        self._hold = False
        self._kick = False
        self._wake = asyncio.Event()
        self._manual_fires = 0
        # A handoff waiting for this task to be free, and the depth of the run
        # currently in flight. At most one waits: see `hand`.
        self._handed: Handoff | None = None
        # A finished run waiting on a person, and the chain depth it stopped
        # at -- kept beside it because the runner's own depth moves on if the
        # task runs again before anybody answers.
        self._asking: RunResult | None = None
        self._asking_depth = 0
        self._restore_question()
        self._depth = 0
        self.handoff = handoff
        # The trigger's next fire, once armed. While holding it stays put:
        # the generator sits suspended at its yield instead of spinning.
        self._pending: asyncio.Task[Firing] | None = None
        # A task that says where it works keeps a private copy of it.
        workdir = config.workdir_path(task.spec)
        self.workspace = (
            Workspace(workdir, task.spec.name, config.layout().worktrees())
            if workdir is not None
            else None
        )
        self._tracking = False
        # Where this task's tools work. Built by the daemon, because the container
        # keeper is shared across tasks and the roster is only known there.
        self.tool_context = tool_context

    @property
    def name(self) -> str:
        return self.task.spec.name

    async def _open_change(self) -> Path | None:
        """Give the run a private copy of the project to work in."""
        point = self.workspace
        self._tracking = False
        if point is None:
            return None
        try:
            if not await asyncio.to_thread(point.available):
                log.warning(
                    "task '%s': %s cannot be tracked -- the work will happen there "
                    "directly, and its changes cannot be reviewed or undone",
                    self.name,
                    point.repo,
                )
                return point.repo
            await asyncio.to_thread(point.prepare)
        except WorkspaceError as exc:
            # A repository we cannot use is not a reason to stop working at 3am.
            log.error("task '%s': %s", self.name, exc)
            return point.repo
        self._tracking = True
        return point.worktree

    async def _close_change(self, result: RunResult) -> None:
        """Land the run's work as one change, or leave the branch alone."""
        if not self._tracking or self.workspace is None:
            return
        try:
            change = await asyncio.to_thread(
                self.workspace.commit,
                result.run_id,
                _change_message(result, self.name),
                failed=result.status != "completed",
            )
        except WorkspaceError as exc:
            # The work ran; only the record of it failed. That is not a reason
            # to stop at 3am -- but it has to be visible, and a line in the
            # daemon's log is not. `then:` conditions are written against
            # `run.change`, so a task whose commits keep failing passes its own
            # gate and never hands over, forever, while the board shows a
            # healthy green run that "changed nothing". The run's own stream is
            # where somebody would look, so that is where it goes.
            log.error("task '%s': the change could not be recorded: %s", self.name, exc)
            self.store.append(
                Event(
                    run_id=result.run_id,
                    type="run_change_failed",
                    data={"error": str(exc)},
                )
            )
            return
        if change is None:
            return  # nothing to do is not nothing done

        result.change = change.as_dict()
        self.store.append(
            Event(run_id=result.run_id, type="run_change", data=dict(result.change))
        )

    @property
    def last_result(self) -> RunResult | None:
        return self.results[-1] if self.results else None

    # -- the control seam: the board's three verbs ---------------------------

    def pause(self) -> str:
        """Hold the schedule. Takes effect between runs; due fires are skipped."""
        self._hold = True
        if self.status == "waiting":
            self.status = "paused"
        self._wake.set()
        return self.status

    def resume(self) -> str:
        """Rearm the schedule; the next fire is the next scheduled one.

        Works the same on a task that paused itself: the failure counter
        starts over rather than tripping again on the first bad run.
        """
        self._hold = False
        self._repeat_key, self._repeat_count = None, 0
        if self.status == "paused":
            self.status = "waiting"
        self._wake.set()
        return self.status

    def run_now(self) -> bool:
        """One fire, immediately, outside the schedule -- or False mid-run:
        iterations never overlap, exactly as the triggers promise."""
        if self.status == "running":
            return False
        self._kick = True
        self._wake.set()
        return True

    @property
    def holding(self) -> bool:
        """Whether a hold is on -- by hand, or by this task's own failures."""
        return self._hold

    def hand(self, handoff: Handoff) -> Handoff | None:
        """Take a handoff, and say which one it displaced.

        Unlike run_now this does not refuse mid-run: it parks, and the run loop
        finds it when the current run ends. But **one** parks and the newest
        wins -- the interval trigger's own rule one level up. The caller logs
        what it lost.
        """
        displaced, self._handed = self._handed, handoff
        self._kick = True
        self._wake.set()
        return displaced

    async def _woken(self) -> None:
        """Parked: wait for a verb or shutdown, the trigger left unconsumed."""
        woke = asyncio.ensure_future(self._wake.wait())
        down = asyncio.ensure_future(self.cancel.wait())
        try:
            await asyncio.wait({woke, down}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            woke.cancel()
            down.cancel()
            self._wake.clear()

    def _drop_pending(self) -> None:
        """Skip a fire that came due while holding: skipped, not queued."""
        assert self._pending is not None and self._pending.done()
        try:
            self._pending.result()
        except (StopAsyncIteration, asyncio.CancelledError):
            pass
        self._pending = None

    async def _next_fire(self, fires: AsyncIterator[Firing]) -> Firing | None:
        """The runner's ear: the trigger raced against the board's verbs.

        Returns the fire to run next, or None when the daemon is shutting down
        or the schedule is over. A run-now wins over everything, even a hold; a
        hold leaves the trigger unconsumed, so a loop trigger sits suspended at
        its yield instead of spinning through a pause.
        """
        while not self.cancel.is_set():
            if self._kick:
                self._kick = False
                self._manual_fires += 1
                # A handoff and a run-now are the same kick; only the reason
                # differs, and the reason is what the run will record.
                reason = self._handed.reason if self._handed else "run now"
                return Firing(
                    iteration=self._manual_fires, at=datetime.now(), reason=reason
                )
            if self._hold:
                self.status = "paused"
                if self._pending is not None and self._pending.done():
                    self._drop_pending()
                await self._woken()
                continue
            if self._pending is None:
                self._pending = asyncio.ensure_future(anext(fires))
            woke = asyncio.ensure_future(self._wake.wait())
            try:
                await asyncio.wait(
                    {self._pending, woke}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                woke.cancel()
                self._wake.clear()
            if self._pending.done() and not self._hold and not self._kick:
                try:
                    fire = self._pending.result()
                except StopAsyncIteration:
                    return None
                self._pending = None
                if self.cancel.is_set():
                    return None
                return fire
        return None

    async def _quiet(self, fires: AsyncIterator[Firing]) -> None:
        """Leave nothing running behind: the held anext, then the generator."""
        if self._pending is not None:
            self._pending.cancel()
            try:
                await self._pending
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            self._pending = None
        close = getattr(fires, "aclose", None)
        if close is not None:  # every real trigger is an async generator
            await close()

    async def run(self) -> None:
        log.info("task '%s' armed (%s)", self.name, self.trigger.describe)
        fires = self.trigger.fires(self.cancel)
        try:
            while True:
                fire = await self._next_fire(fires)
                if fire is None or not await self._one_run(fire):
                    break
        finally:
            await self._quiet(fires)
        log.info("task '%s' stopped", self.name)

    async def _one_run(self, fire: Firing) -> bool:
        """One firing, end to end. False when the runner should stand down."""
        # Taken whether or not the read below succeeds: a handoff left parked
        # would ride along with whatever fired next, which is not what it was.
        handed, self._handed = self._handed, None
        self._depth = handed.depth if handed is not None else 0
        try:
            payload = self.task.read_input(self.config)
        except PoieoError as exc:
            log.error("task '%s': %s", self.name, exc)
            return self.task.spec.on_error != "stop"
        if handed is not None:
            # Merged last: what woke this run is the most specific thing it
            # knows. `sender`, not `from` -- expressions are parsed as Python,
            # where `input.from.change` would not even parse.
            payload["sender"] = handed.result

        log.info(
            "task '%s' firing (iteration %d, %s)",
            self.name,
            fire.iteration,
            fire.reason,
        )
        run_id = new_run_id()
        self.status, self.current_run_id = "running", run_id
        workdir = await self._open_change()
        try:
            result = await execute(
                self.task.graph,
                self.task.binding,
                self.pool,
                self.store,
                input=payload,
                state=dict(self.state) if self.task.spec.carry_state else None,
                task=self.name,
                project=self.config.display_name,
                # What actually fired this run, not the schedule it may not
                # have used.
                trigger=fire.reason,
                iteration=fire.iteration,
                run_id=run_id,
                cancel=self.cancel,
                workdir=workdir,
                tool_context=self.tool_context,
                finalize=self._close_change,
            )
        finally:
            self.status, self.current_run_id = "waiting", None
        self.results.append(result)
        self._remember(result)
        if self.task.spec.carry_state:
            self.state = result.state

        pause = self._note_outcome(result)
        if result.status == "asking":
            self._park(result)
        elif self.handoff is not None and self.task.spec.then:
            # Ahead of the stand-down below: the run happened, so what it says
            # should work next does not depend on this runner carrying on.
            self.handoff(self, result, self._depth)

        if result.status == "completed":
            log.info(
                "task '%s' run %s completed in %d step(s) [%s]",
                self.name,
                result.run_id,
                result.steps,
                " -> ".join(result.path),
            )
        elif result.status != "asking":
            # Asking is not one of these. `_park` has already said so, at the
            # level a question deserves; reporting it here as well would put
            # `run ... asking: None` in the log at ERROR every time a card did
            # what it was written to do.
            log.error(
                "task '%s' run %s %s: %s",
                self.name,
                result.run_id,
                result.status,
                result.error,
            )
            if self.task.spec.on_error == "stop" and result.status == "failed":
                log.error("task '%s' stopping (on_error: stop)", self.name)
                return False

        if self.on_run:
            self.on_run(self.name, result)

        if pause:
            said = (result.cause or {}).get("said") or result.error or "the same failure"
            log.error(
                "task '%s' paused after %d identical failures: %s",
                self.name, PAUSE_AFTER, said,
            )
            self._journal_pause(said)
            # Parks at the next _next_fire rather than standing down: the
            # coroutine has to stay alive for resume() to have anyone to wake.
            self._hold = True
            self.status = "paused"
        return True

    def _asking_path(self) -> Path | None:
        """Where this task's outstanding question waits out a restart."""
        card = self.config.cards_by_task.get(self.name)
        if card is None:
            return None
        return self.config.layout().asking() / f"{card.slug}.json"

    def _restore_question(self) -> None:
        """Pick up a question the last daemon left unanswered.

        A question that a restart eats is worse than one never asked: the run
        that raised it is gone, so the only way back to the decision is to run
        the card again -- which for the card this is written for means doing
        the whole night's work a second time.

        Anything wrong with the file is a warning and no question. It is
        derived from a run that already happened, and the recovery is the same
        one the user has anyway.
        """
        path = self._asking_path()
        if path is None or not path.exists():
            return
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
            depth = kept.pop("depth", 0)
            self._asking, self._asking_depth = RunResult(**kept), int(depth)
        except (OSError, ValueError, TypeError) as exc:
            log.warning(
                "task '%s': could not read the question left at %s: %s", self.name, path, exc
            )
            return
        log.info(
            "task '%s' is still waiting on you: %s",
            self.name,
            (self._asking.asked or {}).get("question", ""),
        )

    def _keep_question(self) -> None:
        """Write the outstanding question down, or forget it once answered."""
        path = self._asking_path()
        if path is None:
            return
        try:
            if self._asking is None:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            kept = asdict(self._asking) | {"depth": self._asking_depth}
            path.write_text(
                json.dumps(kept, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as exc:
            # The question still stands in this process; it just will not
            # outlive it. Worth saying, never worth failing the run over.
            log.warning("task '%s': could not keep the question: %s", self.name, exc)

    def _park(self, result: RunResult) -> None:
        """Hold a run that ended by asking, until somebody answers it.

        Its `then:` is **deferred, not skipped**: nothing downstream moves, and
        the branch that would have fired is evaluated the moment an answer
        arrives. The runner itself is free -- the run really did end -- so the
        task keeps to its schedule while it waits.
        """
        if self._asking is not None:
            # Newest wins, as a parked handoff does. A question about a merge
            # from three weeks ago is worse than no question: it reads as a
            # decision still open when the thing it was about has moved on.
            log.warning(
                "task '%s' asked again before the last question was answered "
                "(%r); the older one is dropped.",
                self.name,
                (self._asking.asked or {}).get("question", ""),
            )
        self._asking, self._asking_depth = result, self._depth
        self._keep_question()
        log.info(
            "task '%s' run %s is waiting on you: %s [%s]",
            self.name,
            result.run_id,
            (result.asked or {}).get("question", ""),
            "/".join((result.asked or {}).get("choices", [])),
        )

    def asking(self) -> RunResult | None:
        """The run waiting on a person, if there is one."""
        return self._asking

    def answer(self, choice: str) -> bool:
        """Answer the outstanding question. False when there is nothing to answer.

        Only what the node offered: an answer read loosely is the guess this
        node exists to replace, and it would be read here rather than by the
        person who typed it.
        """
        result = self._asking
        if result is None:
            log.warning("task '%s' is not waiting on an answer", self.name)
            return False
        choices = (result.asked or {}).get("choices", [])
        if choice not in choices:
            log.warning(
                "task '%s' was not offered %r; it asked for one of %s",
                self.name,
                choice,
                "/".join(choices),
            )
            return False

        result.answer = choice
        # It is finished now, and finished is what it is: a `then:` written as
        # `run.status == 'completed'` should see the run it waited for.
        result.status = "completed"
        self._asking = None
        # Before anything else it might fire: a question answered twice would
        # hand the same work on twice.
        self._keep_question()
        # Said out loud before the record is revised. `_remember` below rewrites
        # this run's record from `asking` to `completed` -- the one case where
        # a record legitimately changes after the fact -- and a record that
        # changed with nothing in the log to account for it is the one thing
        # this project keeps a log to avoid.
        self.store.append(
            Event(
                run_id=result.run_id,
                type="run_answered",
                data={"answer": choice, "node": (result.asked or {}).get("node")},
            )
        )
        self._remember(result, replace=True)
        if self.handoff is not None and self.task.spec.then:
            self.handoff(self, result, self._asking_depth)
        return True

    def _note_outcome(self, result: Any) -> bool:
        """Track consecutive identical failures; True when it is time to pause.

        "Identical" means the same cause slug, or the same raw error text when
        nothing classified -- so one unreachable server counts as one thing
        however its message varies.
        """
        if result.status in ("completed", "asking"):
            # Asking is not failing. A card that ends every night by putting
            # the same question to somebody would otherwise pause itself for
            # doing exactly what it was written to do.
            self._repeat_key, self._repeat_count = None, 0
            return False
        key = (result.cause or {}).get("slug") or result.error or result.status
        if key == self._repeat_key:
            self._repeat_count += 1
        else:
            self._repeat_key, self._repeat_count = key, 1
        return self._repeat_count >= PAUSE_AFTER

    def _journal_pause(self, said: str) -> None:
        """The reason must survive to the morning, beside the failures."""
        task = self.config.cards_by_task.get(self.name)
        if task is None:
            return
        try:
            append_journal(
                task.journal_path(),
                "failed",
                f"paused after {PAUSE_AFTER} identical failures: {said}. "
                f"Fix the cause, then resume it from the board or restart the daemon.",
                title=task.name,
            )
        except OSError as exc:
            log.warning("task '%s': could not journal the pause: %s", self.name, exc)

    def _remember(self, result: RunResult, replace: bool = False) -> None:
        task = self.config.cards_by_task.get(self.name)
        if task is not None:
            record_run(task, result, replace=replace)


@dataclass(slots=True)
class LoadedProject:
    """One project the daemon runs: its paths, its run history, its tasks.

    Everything a task needs that is not the task itself hangs off here rather
    than off the daemon -- where its runs are written, which other cards it may
    leave a note for, whether the project learns. The daemon is about to hold
    more than one of these, and each of those questions has a different answer
    per project.
    """

    config: DaemonConfig
    store: RunStore
    tasks: list[LoadedTask]


def _no_two_projects_alike(projects: list[LoadedProject]) -> None:
    """Refuse at launch when two projects answer to the same name.

    A project's name is what tells it from another one -- on the board, in a
    run record, in the address of every control route. Two called `poieo` make
    each of those mean whichever answered first.

    This is the constraint that belongs here. Requiring *task* names to be
    unique across projects, which is what stood here first, made the daemon
    refuse the ordinary case: every project has a `chores`. Names collide by
    default, too -- a project falls back to its folder's name, and a worktree
    is a second folder called the same thing as the first -- which is exactly
    what `name:` in poieo.yaml is for.
    """
    seen: dict[str, Path | None] = {}
    for project in projects:
        name = project.config.display_name
        if name in seen:
            raise SpecError(
                f"two projects are both called '{name}' ({seen[name]} and "
                f"{project.config.source_path}). Give one of them a `name:` "
                f"in its poieo.yaml -- it is what a board, a run record and "
                f"every control route call it by"
            )
        seen[name] = project.config.source_path


class Daemon:
    """Owns the provider pools, the running tasks, and the shutdown handshake."""

    def __init__(
        self,
        config: DaemonConfig | Sequence[DaemonConfig],
        *,
        store: RunStore | None = None,
        on_run: RunCallback | None = None,
        web_port: int | None = None,
    ):
        # One project or several. A caller with one passes it bare, which is
        # every caller there was before the board learned to switch between
        # them, and an injected `store` belongs to that one.
        configs = [config] if isinstance(config, DaemonConfig) else list(config)
        if not configs:
            raise SpecError("a daemon needs at least one project to run")
        if store is not None and len(configs) > 1:
            # An injected store is one store, and a project keeps its own
            # history. Handing the same one to several would file every
            # project's runs in whichever folder it happened to point at.
            raise SpecError(
                "a store can only be handed to a daemon running one project; "
                "with several, each keeps its own"
            )

        self.projects = [
            LoadedProject(
                config=each,
                store=self._history_for(each, store, web_port),
                tasks=load_tasks(each),
            )
            for each in configs
        ]
        _no_two_projects_alike(self.projects)
        self._merged: MergedStore | None = None
        self.web_port = web_port
        self.on_run = on_run
        self.cancel = asyncio.Event()
        # One pool per distinct binding file: clients are reused across tasks,
        # and across projects -- two projects naming one binding file mean one
        # set of clients, which is the point of keying on the file.
        self.pools: dict[str, ProviderPool] = {}
        # One container per distinct folder-and-settings, for the same reason.
        self.containers: Any = (
            make_container_pool()
            if any(f.spec.isolation for f in self.tasks)
            else None
        )
        self.runners: list[TaskRunner] = []

    @staticmethod
    def _history_for(
        config: DaemonConfig, store: RunStore | None, web_port: int | None
    ) -> RunStore:
        """Where this project's runs are written, wrapped to publish if served.

        A store per project, because a store is where a project keeps its own
        history -- sharing one would file a task's runs in a folder its own
        `poieo runs` cannot see.
        """
        history = store or RunStore(config.layout().runs())
        if web_port is not None and not isinstance(history, BroadcastStore):
            history = BroadcastStore(history)
        return history

    # -- asked of the daemon, answered by the projects ------------------------
    #
    # The daemon's insides ask a project directly. These are for the seam that
    # is not project-aware yet: the web API, whose routes still take a task
    # name and no project. That is also why two projects may not share one.

    @property
    def config(self) -> DaemonConfig:
        """The first project's. Only the API asks, and only for its paths."""
        return self.projects[0].config

    @property
    def store(self) -> RunStore:
        """Every project's history, read as one -- and the one store itself
        when there is only one, because then there is nothing to merge and a
        wrapper would only stand between the board and the answer."""
        if len(self.projects) == 1:
            return self.projects[0].store
        if self._merged is None:
            self._merged = MergedStore([project.store for project in self.projects])
        return self._merged

    @property
    def tasks(self) -> list[LoadedTask]:
        """Every task the daemon runs, whichever project it came from."""
        return [task for project in self.projects for task in project.tasks]

    def _postbox_for(self, project: LoadedProject, task: LoadedTask) -> Any:
        """A task that took the notes toolset gets one; nobody else does.

        The recipients are that project's cards and no others. A note is a
        line written into another card's journal, and a journal is a file in
        one project's memory -- reaching across would be one project writing
        into another's folder.
        """
        card = project.config.cards_by_task.get(task.spec.name)
        if card is None or "notes" not in (card.tools or []):
            return None
        from ..tools.notes import Postbox

        return Postbox(
            sender=task.spec.name,
            recipients={
                name: other.journal_path()
                for name, other in project.config.cards_by_task.items()
            },
        )

    def _hands_for(self, project: LoadedProject, task: LoadedTask) -> ToolContext:
        return ToolContext(
            isolation=task.spec.isolation,
            containers=self.containers,
            postbox=self._postbox_for(project, task),
            # The *project's* cache, never one worked out from the workdir:
            # a workdir with no marker answers as its own project, and the
            # cache would land inside the repository the run commits.
            build_cache=project.config.layout().cache() / "builds",
        )

    def _runners(self) -> list[TaskRunner]:
        return [
            TaskRunner(
                task,
                project.config,
                self._pool_for(task),
                project.store,
                self.cancel,
                self.on_run,
                self._hands_for(project, task),
                # Bound, so it resolves against self.runners at call time --
                # which is after this list has been built and assigned.
                self._hand_off,
            )
            for project in self.projects
            for task in project.tasks
        ]

    # -- handing one task's finished work to the task it named ---------------

    def _chosen(self, sender: TaskRunner, run: dict[str, Any]) -> Branch | None:
        """The first branch that matches, router-style, or None.

        A branch that will not evaluate is skipped rather than fatal: unlike a
        router, the sender has already finished and landed its change, so there
        is nothing left to fail.
        """
        scope = {"run": wrap(run)}
        for index, branch in enumerate(sender.task.spec.then):
            try:
                if evaluate(branch.when, scope):
                    return branch
            except ExpressionError as exc:
                log.warning(
                    "task '%s' then[%d] (%r): %s -- treating it as no match.",
                    sender.name,
                    index,
                    branch.when,
                    exc,
                )
        return None

    def _hand_off(self, sender: TaskRunner, result: RunResult, depth: int) -> None:
        run = handoff_scope(result)
        branch = self._chosen(sender, run)
        if branch is None or branch.to is None:
            return  # nothing matched, or a branch that deliberately stops

        if depth >= MAX_CHAIN:
            log.warning(
                "task '%s' would hand off to '%s', but this chain has already "
                "made %d handoffs and stops here. Check for a loop.",
                sender.name,
                branch.to,
                depth,
            )
            return

        # Within the sender's own project. `check_handoffs()` already refuses a
        # `to:` that names nothing in the project, so a cross-project hop cannot
        # be reached from a valid config -- but the search should say which
        # namespace it means rather than rely on names being unique daemon-wide,
        # which is a rule this daemon enforces today and will not forever.
        target = next(
            (
                r
                for r in self.runners
                if r.name == branch.to and r.config is sender.config
            ),
            None,
        )
        if target is None:
            # Disabled, so it has no runner. check_handoffs already said so at
            # load; saying it again per run would be noise.
            return
        if target.holding:
            log.warning(
                "task '%s' handed off to '%s', which is paused: dropped. "
                "Resume it and the next handoff lands.",
                sender.name,
                branch.to,
            )
            return

        label = branch.label or branch.when
        displaced = target.hand(
            Handoff(result=run, reason=f"after {sender.name} ({label})", depth=depth + 1)
        )
        if displaced is not None:
            # Always said out loud: a loss nobody hears about is what the
            # one-waits rule would otherwise buy.
            log.warning(
                "task '%s' was still busy, so an earlier handoff (%s) was "
                "dropped in favour of this one.",
                branch.to,
                displaced.reason,
            )

    def _pool_for(self, task: LoadedTask) -> ProviderPool:
        if task.binding_key not in self.pools:
            self.pools[task.binding_key] = ProviderPool(task.binding)
        return self.pools[task.binding_key]

    def stop(self) -> None:
        """Request a graceful shutdown; in-flight runs finish their current node."""
        self.cancel.set()

    # -- learning while nothing else is running ------------------------------

    def _ready_to_learn(self, project: LoadedProject) -> bool:
        """Double opt-in (the config key and the folder), and learning
        always yields to work: not one runner may be mid-run.

        Not one runner *anywhere*, not just this project's. Learning reads a
        project's run records and rewrites its memory, and it yields to work
        because it would rather be late than contend -- which is as true of
        another project's run as of this one's.
        """
        config = project.config
        if config.learn is None or not config.cards:
            return False
        if not keeps_memory(config.base_dir):
            return False
        return all(runner.status == "waiting" for runner in self.runners)

    async def _learn_once(
        self, project: LoadedProject, spec: Any, pool: ProviderPool
    ) -> None:
        """One guarded attempt. Nothing here may take the daemon down."""
        config = project.config
        folder = config.resolve_path(config.cards)
        try:
            result = await learn_pass(folder, spec, pool)
        except Exception as exc:
            log.warning("the learning pass failed: %s", exc)
            return
        if result is None:
            return
        if result.error is not None:
            log.warning("the learning pass failed and will reread: %s", result.error)
        else:
            log.info(
                "learned from %d record(s): kept %d, set aside %d",
                result.read,
                len(result.kept),
                len(result.set_aside),
            )

    async def _learning_loop(self, project: LoadedProject) -> None:
        from ..binding import load_binding

        config = project.config
        try:
            interval = parse_duration(config.learn)
            spec = load_binding(config.resolve_path(config.binding))
        except Exception as exc:
            log.warning("learning is off: %s", exc)
            return
        async with ProviderPool(spec) as pool:
            while await _sleep_or_cancel(interval, self.cancel):
                if self._ready_to_learn(project):
                    await self._learn_once(project, spec, pool)

    def _install_signals(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._on_signal, sig)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - win32
                pass

    def _on_signal(self, sig: signal.Signals) -> None:
        if self.cancel.is_set():
            log.warning("second %s -- exiting now", sig.name)
            raise SystemExit(1)
        log.info("%s received; finishing in-flight runs", sig.name)
        self.cancel.set()

    async def serve(self, *, install_signals: bool = True) -> list[RunResult]:
        if not self.tasks:
            log.warning(
                "no enabled tasks in %s",
                ", ".join(str(project.config.source_path) for project in self.projects),
            )
            return []
        if install_signals:
            self._install_signals()

        web_task = None
        server = None
        if self.web_port is not None:
            import uvicorn

            _ensure_port_free("127.0.0.1", self.web_port)
            server = uvicorn.Server(
                uvicorn.Config(
                    create_app(self),
                    host="127.0.0.1",
                    port=self.web_port,
                    log_level="warning",
                )
            )
            server.install_signal_handlers = lambda: None
            web_task = asyncio.create_task(server.serve())
            log.info("web observation UI on http://127.0.0.1:%d", self.web_port)

        if self.containers is not None:
            # Whatever an earlier poieo left behind after a crash. Boxes it
            # owned itself are already gone -- shutdown removes them.
            try:
                reclaimed = await sweep_containers()
                if reclaimed:
                    log.info("reclaimed %d abandoned environment(s)", reclaimed)
            except Exception as exc:
                # Tidying is never worth refusing to start over.
                log.warning("could not reclaim old environments: %s", exc)

        self.runners = self._runners()
        # One loop per project that asked for it: `learn:` is a project's key,
        # and two projects learn on their own schedules from their own records.
        learn_tasks = [
            asyncio.create_task(self._learning_loop(project))
            for project in self.projects
            if project.config.learn is not None
        ]
        for project in self.projects:
            if project.config.learn is not None:
                log.info(
                    "'%s' learns every %s, while nothing else is running",
                    project.config.display_name,
                    project.config.learn,
                )
        log.info(
            "poieo daemon up: %d task(s), store at %s",
            len(self.runners),
            ", ".join(str(project.store.root) for project in self.projects),
        )
        try:
            # return_exceptions: one task blowing up must not orphan the others
            # or tear down pools they are still using.
            outcomes = await asyncio.gather(
                *(runner.run() for runner in self.runners), return_exceptions=True
            )
            for runner, outcome in zip(self.runners, outcomes):
                if isinstance(outcome, BaseException):
                    log.exception(
                        "task '%s' crashed: %s", runner.name, outcome, exc_info=outcome
                    )
        finally:
            self.cancel.set()
            for learn_task in learn_tasks:
                await _stopped(learn_task, "learning pass")
            if web_task is not None:
                server.should_exit = True
                await _stopped(web_task, "web server")
            if self.containers is not None:
                await self.containers.aclose()
            for pool in self.pools.values():
                await pool.aclose()
            log.info("poieo daemon down")
        return [result for runner in self.runners for result in runner.results]
