"""The resident process: keeps flows firing until it is told to stop."""

from __future__ import annotations

import asyncio
import logging
import signal
import socket
from typing import Any, Callable

from ..errors import PoieoError, SpecError
from ..providers import ProviderPool
from ..runtime.context import RunResult, new_run_id
from ..runtime.executor import execute
from ..store import RunStore
from ..task import append_journal
from ..web import BroadcastStore, create_app
from .config import DaemonConfig, LoadedFlow, load_flows

log = logging.getLogger("poieo.daemon")

RunCallback = Callable[[str, RunResult], None]


def _last_output(result: RunResult) -> str:
    """What the model said last: its own one-line summary of the work."""
    for node_id in reversed(result.path):
        value = result.outputs.get(node_id)
        if isinstance(value, str) and value.strip():
            return value
    return "(said nothing)"


def _ensure_port_free(host: str, port: int) -> None:
    """Fail at launch, not after flows have started."""
    with socket.socket() as sock:
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise SpecError(
                f"web port {port} is already in use on {host}: {exc}"
            ) from exc


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
    ):
        self.flow = flow
        self.config = config
        self.pool = pool
        self.store = store
        self.cancel = cancel
        self.on_run = on_run
        self.trigger = flow.spec.trigger.build()
        self.results: list[RunResult] = []
        # Ending state of the last run, replayed into the next when carrying.
        self.state: dict[str, Any] = {}
        self.status: str = "waiting"
        self.current_run_id: str | None = None

    @property
    def name(self) -> str:
        return self.flow.spec.name

    @property
    def last_result(self) -> RunResult | None:
        return self.results[-1] if self.results else None

    async def run(self) -> None:
        log.info("flow '%s' armed (%s)", self.name, self.trigger.describe)
        async for fire in self.trigger.fires(self.cancel):
            if self.cancel.is_set():
                break
            try:
                payload = self.flow.read_input(self.config)
            except PoieoError as exc:
                log.error("flow '%s': %s", self.name, exc)
                if self.flow.spec.on_error == "stop":
                    break
                continue

            log.info(
                "flow '%s' firing (iteration %d, %s)",
                self.name,
                fire.iteration,
                fire.reason,
            )
            run_id = new_run_id()
            self.status, self.current_run_id = "running", run_id
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
                )
            finally:
                self.status, self.current_run_id = "waiting", None
            self.results.append(result)
            self._remember(result)
            if self.flow.spec.carry_state:
                self.state = result.state

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
                    break

            if self.on_run:
                self.on_run(self.name, result)

        log.info("flow '%s' stopped", self.name)

    def _remember(self, result: RunResult) -> None:
        """Add this run to the task's journal, so the next one can read it."""
        task = self.config.tasks_by_flow.get(self.name)
        if task is None:
            return
        if result.status == "completed":
            kind, text = "did", _last_output(result)
        else:
            kind, text = "failed", result.error or result.status
        try:
            append_journal(task.journal_path(), kind, text, title=task.name)
        except OSError as exc:
            # Memory is not worth killing a night's work over.
            log.warning("flow '%s': could not write the journal: %s", self.name, exc)


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
        self.runners: list[FlowRunner] = []

    def _pool_for(self, flow: LoadedFlow) -> ProviderPool:
        if flow.binding_key not in self.pools:
            self.pools[flow.binding_key] = ProviderPool(flow.binding)
        return self.pools[flow.binding_key]

    def stop(self) -> None:
        """Request a graceful shutdown; in-flight runs finish their current node."""
        self.cancel.set()

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

        self.runners = [
            FlowRunner(
                flow,
                self.config,
                self._pool_for(flow),
                self.store,
                self.cancel,
                self.on_run,
            )
            for flow in self.flows
        ]
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
            if web_task is not None:
                server.should_exit = True
                try:
                    await asyncio.wait_for(web_task, timeout=5)
                except (asyncio.TimeoutError, Exception):
                    web_task.cancel()
            for pool in self.pools.values():
                await pool.aclose()
            log.info("poieo daemon down")
        return [result for runner in self.runners for result in runner.results]


async def serve(config: DaemonConfig, **kwargs: Any) -> list[RunResult]:
    return await Daemon(config, **kwargs).serve()
