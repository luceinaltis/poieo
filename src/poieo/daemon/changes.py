"""Verify combined task changes and apply only the user's current permission.

Design: docs/daemon.md
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path
from typing import Callable, Sequence

from ..errors import PoieoError
from ..tools import ToolContext, make_executor
from ..workspace import ApplySpec, Workspace

log = logging.getLogger("poieo.daemon")


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
) -> dict:
    """Finish any in-flight Git write before releasing its copy or returning."""
    stopped = cancel if cancel is not None else asyncio.Event()
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
        )
    )
    while True:
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            # Cancelling to_thread does not stop its worker. Let it reach the
            # next cancellation boundary, including recording a write that won.
            stopped.set()
            if job.cancelled():
                raise


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
) -> dict:
    """Check a fresh combined copy; a competing application requires fresh checks."""
    checks = []
    for _attempt in range(3):
        if cancel is not None and cancel.is_set():
            return {"status": "blocked", "error": "application was stopped", "checks": checks}
        prepared = await asyncio.to_thread(point.prepare_accept, through)
        if isinstance(prepared, dict):
            return {"status": "applied" if "accepted" in prepared else "blocked", **prepared, "checks": checks}
        try:
            if prepared.conflict:
                return {"status": "blocked", "conflict": prepared.conflict, "checks": checks}
            outside = await asyncio.to_thread(point.outside_scope, prepared, policy.paths, protected)
            if outside:
                return {"status": "blocked", "outside_scope": outside, "checks": checks}
            checks = []
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
                        return {"status": "blocked", "error": "verification failed", "checks": checks}
                    checks.append({"command": command, "exit_code": checked.exit_code, "output": checked.output})
                    if checked.exit_code != 0:
                        return {"status": "blocked", "error": "verification failed", "checks": checks}
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
                continue
            return {"status": "applied" if "accepted" in outcome else "blocked", **outcome, "checks": checks}
        finally:
            try:
                await asyncio.to_thread(point.release_prepared, prepared)
            except PoieoError as exc:
                log.warning("could not remove the temporary change: %s", exc)
    return {"status": "blocked", "error": "the project kept changing; try again", "checks": checks}
