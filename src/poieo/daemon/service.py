"""The resident process: keeps flows firing until it is told to stop."""

from __future__ import annotations

import asyncio
import logging
import signal
import socket
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from ..checkpoint import Checkpoint, CheckpointError
from ..errors import PoieoError, SpecError
from ..learn import learn as learn_pass
from ..memory import keeps_memory
from ..providers import ProviderPool
from ..runtime.context import RunResult, new_run_id
from ..runtime.executor import execute
from ..store import Event, RunStore
from ..task import append_journal, closing_line, record_run
from ..tools import Hands, make_box_keeper, sweep_boxes
from ..web import BroadcastStore, create_app
from .config import DaemonConfig, LoadedFlow, load_flows
from .triggers import Fire, _sleep_or_cancel, parse_duration

log = logging.getLogger("poieo.daemon")

RunCallback = Callable[[str, RunResult], None]


def _ensure_port_free(host: str, port: int) -> None:
    """Fail at launch, not after flows have started."""
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

    ``wait_for`` cancels the task and awaits that cancellation before it
    raises, so there is nothing left here to cancel afterwards. What is left
    is the reason, and shutdown used to swallow it: a learning pass that blew
    up at 3am went down with the daemon without leaving a word behind.

    Nothing here may keep the daemon from finishing -- the pools and the boxes
    still have to be closed below.
    """
    try:
        await asyncio.wait_for(task, timeout=SHUTDOWN_GRACE)
    except asyncio.TimeoutError:
        log.warning("the %s did not stop within %gs; leaving it", what, SHUTDOWN_GRACE)
    except Exception as exc:
        log.warning("the %s stopped badly: %s", what, exc)


def _change_message(result: RunResult, flow: str) -> str:
    """The model's own summary when it produced one -- that is what a reader sees.

    The same reading the journal and the run record use, shaped for a commit
    subject: one line, and short enough to sit in a `git log --oneline`.
    """
    said = closing_line(result, fallback="")
    if not said:
        return f"poieo {flow} {result.run_id}"
    return said.strip().splitlines()[0][:72]


# Staying up is the default; staying up while failing identically is not
# resilience, it is noise. A constant, not a setting -- a knob nobody asked
# for would be configuration for its own sake.
PAUSE_AFTER = 3

# How many finished runs a runner keeps in memory. A RunResult carries the
# run's whole outputs and state, and only the tail is ever read: last_result
# by the web API, one pass's worth by --once. A loop flow with no cooldown
# otherwise accumulates every output of every night for the daemon's lifetime.
RESULTS_KEPT = 20


class FlowRunner:
    """Drives one flow: trigger -> run -> carry state -> repeat."""

    def __init__(
        self,
        flow: LoadedFlow,
        config: DaemonConfig,
        pool: ProviderPool,
        store: RunStore,
        cancel: asyncio.Event,
        on_run: RunCallback | None = None,
        hands: Any = None,
    ):
        self.flow = flow
        self.config = config
        self.pool = pool
        self.store = store
        self.cancel = cancel
        self.on_run = on_run
        self.trigger = flow.spec.trigger.build()
        self.results: deque[RunResult] = deque(maxlen=RESULTS_KEPT)
        # Ending state of the last run, replayed into the next when carrying.
        self.state: dict[str, Any] = {}
        self.status: str = "waiting"
        # Consecutive failures sharing one cause; a completed run resets it.
        self._repeat_key: str | None = None
        self._repeat_count: int = 0
        self.current_run_id: str | None = None
        # The control seam: the board's three verbs poke these, and the run
        # loop reads them between runs. All on one event loop -- the web
        # server shares it -- so flags and an Event are the whole mechanism.
        self._hold = False
        self._kick = False
        self._wake = asyncio.Event()
        self._manual_fires = 0
        # The trigger's next fire, once armed. While holding it stays put:
        # the generator sits suspended at its yield instead of spinning.
        self._pending: asyncio.Task[Fire] | None = None
        # A flow that says where it works keeps a private copy of it.
        workdir = config.workdir_path(flow.spec)
        self.checkpoint = (
            Checkpoint(workdir, flow.spec.name, config.store_path())
            if workdir is not None
            else None
        )
        self._tracking = False
        # Where this task's tools work. Built by the daemon, because the box
        # keeper is shared across tasks and the roster is only known there.
        self.hands = hands

    @property
    def name(self) -> str:
        return self.flow.spec.name

    async def _open_change(self) -> Path | None:
        """Give the run a private copy of the project to work in."""
        point = self.checkpoint
        self._tracking = False
        if point is None:
            return None
        try:
            if not await asyncio.to_thread(point.available):
                log.warning(
                    "flow '%s': %s cannot be tracked -- the work will happen there "
                    "directly, and its changes cannot be reviewed or undone",
                    self.name,
                    point.repo,
                )
                return point.repo
            await asyncio.to_thread(point.prepare)
        except CheckpointError as exc:
            # A repository we cannot use is not a reason to stop working at 3am.
            log.error("flow '%s': %s", self.name, exc)
            return point.repo
        self._tracking = True
        return point.worktree

    async def _close_change(self, result: RunResult) -> None:
        """Land the run's work as one change, or leave the branch alone."""
        if not self._tracking or self.checkpoint is None:
            return
        try:
            change = await asyncio.to_thread(
                self.checkpoint.commit,
                result.run_id,
                _change_message(result, self.name),
                failed=result.status != "completed",
            )
        except CheckpointError as exc:
            log.error("flow '%s': the change could not be recorded: %s", self.name, exc)
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

        Works the same on a flow that paused itself: the failure counter
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

    async def _next_fire(self, fires: AsyncIterator[Fire]) -> Fire | None:
        """The runner's ear: the trigger raced against the board's verbs.

        Returns the fire to run next, or None when the daemon is shutting
        down or the schedule is over. A run-now wins over everything, even a
        hold; a hold stops the trigger from being consumed at all, so a loop
        trigger sits suspended at its yield instead of spinning through a
        pause, and at most one already-due fire is dropped in favour of the
        next scheduled one.
        """
        while not self.cancel.is_set():
            if self._kick:
                self._kick = False
                self._manual_fires += 1
                return Fire(
                    iteration=self._manual_fires, at=datetime.now(), reason="run now"
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

    async def _quiet(self, fires: AsyncIterator[Fire]) -> None:
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
        log.info("flow '%s' armed (%s)", self.name, self.trigger.describe)
        fires = self.trigger.fires(self.cancel)
        try:
            while True:
                fire = await self._next_fire(fires)
                if fire is None or not await self._one_run(fire):
                    break
        finally:
            await self._quiet(fires)
        log.info("flow '%s' stopped", self.name)

    async def _one_run(self, fire: Fire) -> bool:
        """One firing, end to end. False when the runner should stand down."""
        try:
            payload = self.flow.read_input(self.config)
        except PoieoError as exc:
            log.error("flow '%s': %s", self.name, exc)
            return self.flow.spec.on_error != "stop"

        log.info(
            "flow '%s' firing (iteration %d, %s)",
            self.name,
            fire.iteration,
            fire.reason,
        )
        run_id = new_run_id()
        self.status, self.current_run_id = "running", run_id
        workdir = await self._open_change()
        try:
            result = await execute(
                self.flow.graph,
                self.flow.binding,
                self.pool,
                self.store,
                input=payload,
                state=dict(self.state) if self.flow.spec.carry_state else None,
                flow=self.name,
                trigger=self.trigger.describe,
                iteration=fire.iteration,
                run_id=run_id,
                cancel=self.cancel,
                workdir=workdir,
                hands=self.hands,
                finalize=self._close_change,
            )
        finally:
            self.status, self.current_run_id = "waiting", None
        self.results.append(result)
        self._remember(result)
        if self.flow.spec.carry_state:
            self.state = result.state

        pause = self._note_outcome(result)
        if result.status == "completed":
            log.info(
                "flow '%s' run %s completed in %d step(s) [%s]",
                self.name,
                result.run_id,
                result.steps,
                " -> ".join(result.path),
            )
        else:
            log.error(
                "flow '%s' run %s %s: %s",
                self.name,
                result.run_id,
                result.status,
                result.error,
            )
            if self.flow.spec.on_error == "stop" and result.status == "failed":
                log.error("flow '%s' stopping (on_error: stop)", self.name)
                return False

        if self.on_run:
            self.on_run(self.name, result)

        if pause:
            said = (result.cause or {}).get("said") or result.error or "the same failure"
            log.error(
                "flow '%s' paused after %d identical failures: %s",
                self.name, PAUSE_AFTER, said,
            )
            self._journal_pause(said)
            # Parks at the next _next_fire rather than standing down: the
            # coroutine has to stay alive for resume() to have anyone to wake.
            self._hold = True
            self.status = "paused"
        return True

    def _note_outcome(self, result: Any) -> bool:
        """Track consecutive identical failures; True when it is time to pause.

        "Identical" means the same cause slug -- or the same raw error text
        when nothing classified -- so Ollama down at 2am counts as one thing
        however its message varies, while a genuinely new failure restarts
        the count.
        """
        if result.status == "completed":
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
        task = self.config.tasks_by_flow.get(self.name)
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

    def _remember(self, result: RunResult) -> None:
        task = self.config.tasks_by_flow.get(self.name)
        if task is not None:
            record_run(task, result)


class Daemon:
    """Owns the provider pools, the flow tasks, and the shutdown handshake."""

    def __init__(
        self,
        config: DaemonConfig,
        *,
        store: RunStore | None = None,
        on_run: RunCallback | None = None,
        web_port: int | None = None,
    ):
        self.config = config
        self.flows = load_flows(config)
        base_store = store or RunStore(config.store_path())
        if web_port is not None and not isinstance(base_store, BroadcastStore):
            base_store = BroadcastStore(base_store)
        self.store = base_store
        self.web_port = web_port
        self.on_run = on_run
        self.cancel = asyncio.Event()
        # One pool per distinct binding file: clients are reused across flows.
        self.pools: dict[str, ProviderPool] = {}
        # One box per distinct folder-and-settings, for the same reason.
        self.boxes: Any = (
            make_box_keeper()
            if any(f.spec.isolation for f in self.flows)
            else None
        )
        self.runners: list[FlowRunner] = []

    def _postbox_for(self, flow: LoadedFlow) -> Any:
        """A task that took the notes toolset gets one; nobody else does."""
        task = self.config.tasks_by_flow.get(flow.spec.name)
        if task is None or "notes" not in (task.tools or []):
            return None
        from ..tools.notes import Postbox

        return Postbox(
            sender=flow.spec.name,
            recipients={
                name: other.journal_path()
                for name, other in self.config.tasks_by_flow.items()
            },
        )

    def _hands_for(self, flow: LoadedFlow) -> Hands:
        return Hands(
            isolation=flow.spec.isolation,
            boxes=self.boxes,
            postbox=self._postbox_for(flow),
        )

    def _runners(self) -> list[FlowRunner]:
        return [
            FlowRunner(
                flow,
                self.config,
                self._pool_for(flow),
                self.store,
                self.cancel,
                self.on_run,
                self._hands_for(flow),
            )
            for flow in self.flows
        ]

    def _pool_for(self, flow: LoadedFlow) -> ProviderPool:
        if flow.binding_key not in self.pools:
            self.pools[flow.binding_key] = ProviderPool(flow.binding)
        return self.pools[flow.binding_key]

    def stop(self) -> None:
        """Request a graceful shutdown; in-flight runs finish their current node."""
        self.cancel.set()

    # -- learning while nothing else is running ------------------------------

    def _ready_to_learn(self) -> bool:
        """Double opt-in (the config key and the folder), and learning
        always yields to work: not one runner may be mid-run."""
        if self.config.learn is None or not self.config.tasks:
            return False
        if not keeps_memory(self.config.resolve_path(self.config.tasks)):
            return False
        return all(runner.status == "waiting" for runner in self.runners)

    async def _learn_once(self, spec: Any, pool: ProviderPool) -> None:
        """One guarded attempt. Nothing that happens here may take the
        daemon down -- the box-sweep rule, applied continuously."""
        project = self.config.resolve_path(self.config.tasks)
        try:
            result = await learn_pass(project, spec, pool)
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

    async def _learning_loop(self) -> None:
        from ..binding import load_binding

        try:
            interval = parse_duration(self.config.learn)
            spec = load_binding(self.config.resolve_path(self.config.binding))
        except Exception as exc:
            log.warning("learning is off: %s", exc)
            return
        async with ProviderPool(spec) as pool:
            while await _sleep_or_cancel(interval, self.cancel):
                if self._ready_to_learn():
                    await self._learn_once(spec, pool)

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
        if not self.flows:
            log.warning("no enabled flows in %s", self.config.source_path)
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

        if self.boxes is not None:
            # Whatever an earlier poieo left behind after a crash. Boxes it
            # owned itself are already gone -- shutdown removes them.
            try:
                reclaimed = await sweep_boxes()
                if reclaimed:
                    log.info("reclaimed %d abandoned environment(s)", reclaimed)
            except Exception as exc:
                # Tidying is never worth refusing to start over.
                log.warning("could not reclaim old environments: %s", exc)

        self.runners = self._runners()
        learn_task = None
        if self.config.learn is not None:
            learn_task = asyncio.create_task(self._learning_loop())
            log.info("learning every %s, while nothing else is running", self.config.learn)
        log.info(
            "poieo daemon up: %d flow(s), store at %s",
            len(self.runners),
            self.store.root,
        )
        try:
            # return_exceptions: one flow blowing up must not orphan the others
            # or tear down pools they are still using.
            outcomes = await asyncio.gather(
                *(runner.run() for runner in self.runners), return_exceptions=True
            )
            for runner, outcome in zip(self.runners, outcomes):
                if isinstance(outcome, BaseException):
                    log.exception(
                        "flow '%s' crashed: %s", runner.name, outcome, exc_info=outcome
                    )
        finally:
            self.cancel.set()
            if learn_task is not None:
                await _stopped(learn_task, "learning pass")
            if web_task is not None:
                server.should_exit = True
                await _stopped(web_task, "web server")
            if self.boxes is not None:
                await self.boxes.aclose()
            for pool in self.pools.values():
                await pool.aclose()
            log.info("poieo daemon down")
        return [result for runner in self.runners for result in runner.results]
