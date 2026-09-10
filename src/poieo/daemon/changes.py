"""Verify combined task changes and apply only the user's current permission.

Design: docs/daemon.md
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path
from typing import Awaitable, Callable, Sequence, TypeVar

from ..errors import PoieoError
from ..tools import ToolContext, make_executor
from ..workspace import ApplySpec, PreparedChange, Workspace

log = logging.getLogger("poieo.daemon")
T = TypeVar("T")
Repair = Callable[[PreparedChange, dict], Awaitable[dict]]


async def finish_write(
    work: Awaitable[T], *, propagate_cancel: bool = False, cancelled: asyncio.Event | None = None
) -> T:
    """Keep ownership until a started write and its record have finished."""
    job = asyncio.ensure_future(work)
    interrupted = False
    while True:
        try:
            result = await asyncio.shield(job)
            break
        except asyncio.CancelledError:
            interrupted = True
            if cancelled is not None:
                cancelled.set()
            if job.cancelled():
                raise
        except Exception:
            if interrupted and propagate_cancel:
                raise asyncio.CancelledError from None
            raise
    if interrupted and propagate_cancel:
        raise asyncio.CancelledError
    return result


async def check_and_apply(
    point: Workspace,
    policy: ApplySpec,
    *,
    through: str | None = None,
    manual: bool = False,
    tool_context: ToolContext | None = None,
    cancel: asyncio.Event | None = None,
    authorized: Callable[[], bool] | None = None,
    protected: Sequence[Path] = (),
    repair: Repair | None = None,
) -> dict:
    """Finish any in-flight Git write before releasing its copy or returning."""
    stopped = asyncio.Event()
    if cancel is not None and cancel.is_set():
        stopped.set()

    async def forward_stop() -> None:
        if cancel is not None:
            await cancel.wait()
            stopped.set()

    forwarding = asyncio.create_task(forward_stop())
    repair_state: dict = {}
    job = asyncio.create_task(
        _check_and_apply(
            point,
            policy,
            through=through,
            manual=manual,
            tool_context=tool_context,
            cancel=stopped,
            authorized=authorized,
            protected=protected,
            repair=repair,
            repair_state=repair_state,
        )
    )
    try:
        while True:
            try:
                outcome = await asyncio.shield(job)
                return {**outcome, **({"repair": repair_state["result"]} if repair_state else {})}
            except asyncio.CancelledError:
                # Cancelling to_thread does not stop its worker. Let it reach the
                # next cancellation boundary, including recording a write that won.
                stopped.set()
                if job.cancelled():
                    raise
    finally:
        forwarding.cancel()
        await asyncio.gather(forwarding, return_exceptions=True)


async def _check_and_apply(
    point: Workspace,
    policy: ApplySpec,
    *,
    through: str | None,
    manual: bool,
    tool_context: ToolContext | None,
    cancel: asyncio.Event,
    authorized: Callable[[], bool] | None,
    protected: Sequence[Path],
    repair: Repair | None,
    repair_state: dict,
) -> dict:
    """Check a fresh combined copy; a competing application requires fresh checks."""
    checks = []
    stale_retries = 0

    async def attempt_repair(prepared: PreparedChange, failure: dict) -> bool:
        if repair is None or repair_state or policy.mode != "auto" or cancel.is_set():
            return False
        if authorized is not None and not authorized():
            return False
        repair_state["result"] = await repair(prepared, failure)
        return repair_state["result"].get("ready") is True

    # At most three project versions and one additional pass after repair.
    for _attempt in range(4):
        if cancel is not None and cancel.is_set():
            return {"status": "blocked", "error": "application was stopped", "checks": checks}
        prepared = await asyncio.to_thread(point.prepare_accept, through)
        if isinstance(prepared, dict):
            return {"status": "applied" if "accepted" in prepared else "blocked", **prepared, "checks": checks}
        try:
            outside = await asyncio.to_thread(point.outside_scope, prepared, policy.paths, protected)
            if outside:
                return {"status": "blocked", "outside_scope": outside, "checks": checks}
            if prepared.conflict:
                failure = {"status": "blocked", "conflict": prepared.conflict, "checks": checks}
                if await attempt_repair(prepared, failure):
                    through = prepared.target
                    continue
                return failure
            checks = []
            failure = None
            folder = await asyncio.to_thread(point.check_folder, prepared)
            # A verification copy has a short lifetime. It must not leave a
            # reusable container mounted onto a directory about to disappear.
            context = replace(tool_context, containers=None) if tool_context else None
            async with make_executor(folder, [], context) as executor:
                for command in policy.checks:
                    if cancel is not None and cancel.is_set():
                        return {"status": "blocked", "error": "verification was stopped", "checks": checks}
                    try:
                        running = asyncio.create_task(executor.run_command(command, timeout=policy.timeout))
                        stopping = asyncio.create_task(cancel.wait())
                        try:
                            done, _ = await asyncio.wait([running, stopping], return_when=asyncio.FIRST_COMPLETED)
                            if stopping in done:
                                running.cancel()
                                await asyncio.gather(running, return_exceptions=True)
                                return {"status": "blocked", "error": "verification was stopped", "checks": checks}
                            checked = await running
                        finally:
                            stopping.cancel()
                            await asyncio.gather(stopping, return_exceptions=True)
                    except (PoieoError, OSError) as exc:
                        checks.append({"command": command, "exit_code": None, "output": str(exc)})
                        failure = {"status": "blocked", "error": "verification failed", "checks": checks}
                        break
                    checks.append({"command": command, "exit_code": checked.exit_code, "output": checked.output})
                    if checked.exit_code != 0:
                        failure = {"status": "blocked", "error": "verification failed", "checks": checks}
                        break
            if failure:
                if await attempt_repair(prepared, failure):
                    through = prepared.target
                    continue
                return failure
            if cancel is not None and cancel.is_set():
                return {"status": "blocked", "error": "application was stopped", "checks": checks}
            invalid = await asyncio.to_thread(point.validate_prepared, prepared)
            if invalid:
                return {"status": "blocked", **invalid, "checks": checks}
            if not manual and (policy.mode != "auto" or (authorized is not None and not authorized())):
                return {"status": "review", "checks": checks, "checked_on": prepared.base}
            outcome = await asyncio.to_thread(
                point.apply_prepared,
                prepared,
                permitted=lambda: not cancel.is_set() and (manual or authorized is None or authorized()),
            )
            if outcome.get("revoked"):
                if cancel.is_set():
                    return {"status": "blocked", "error": "application was stopped", "checks": checks}
                return {"status": "review", "checks": checks, "checked_on": prepared.base}
            if outcome.get("stale") == "the project changed during verification":
                stale_retries += 1
                if stale_retries >= 3:
                    break
                continue
            return {"status": "applied" if "accepted" in outcome else "blocked", **outcome, "checks": checks}
        finally:
            try:
                await asyncio.to_thread(point.release_prepared, prepared)
            except PoieoError as exc:
                log.warning("could not remove the temporary change: %s", exc)
    return {"status": "blocked", "error": "the project kept changing; try again", "checks": checks}
