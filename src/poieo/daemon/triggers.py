"""Triggers decide *when* a task fires; the daemon decides what happens then.

Each is an async generator that yields a :class:`Firing` and **only resumes once
the run has finished** -- which is what makes ``loop`` a true "run
continuously" mode instead of a queue piling up behind a slow model.

Design: docs/daemon.md
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator

from ..cron import CronSchedule
from ..errors import SpecError
from ..task import TriggerSpec, humanize, parse_duration


@dataclass(slots=True)
class Firing:
    """One scheduled activation of a task."""

    iteration: int
    at: datetime
    reason: str


def build_trigger(spec: TriggerSpec) -> Trigger:
    """The trigger a task's schedule settings ask for.

    A function beside the trigger classes rather than a method on the spec:
    the spec lives in ``task.py``, below the daemon, and must not know what
    waits on it.
    """
    if spec.type == "interval":
        if spec.every is None:
            raise SpecError("interval trigger requires 'every'")
        return IntervalTrigger(
            every=parse_duration(spec.every),
            jitter=parse_duration(spec.jitter),
            run_at_start=spec.run_at_start,
            max_iterations=spec.max_iterations,
        )
    if spec.type == "cron":
        if not spec.expression:
            raise SpecError("cron trigger requires 'expression'")
        return CronTrigger(
            schedule=CronSchedule(spec.expression),
            max_iterations=spec.max_iterations,
        )
    if spec.type == "loop":
        return LoopTrigger(
            cooldown=parse_duration(spec.cooldown),
            max_iterations=spec.max_iterations,
        )
    return ManualTrigger(max_iterations=spec.max_iterations)


async def _sleep_or_cancel(seconds: float, cancel: asyncio.Event) -> bool:
    """Sleep, returning False if shutdown was requested first."""
    if seconds <= 0:
        return not cancel.is_set()
    try:
        await asyncio.wait_for(cancel.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return True
    return False


class Trigger:
    """Base trigger. Subclasses implement :meth:`fires`."""

    describe: str = "manual"

    def __init__(self, max_iterations: int | None = None):
        self.max_iterations = max_iterations

    def _exhausted(self, iteration: int) -> bool:
        return self.max_iterations is not None and iteration > self.max_iterations

    async def fires(self, cancel: asyncio.Event) -> AsyncIterator[Firing]:
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator for typing


class ManualTrigger(Trigger):
    """Never fires on its own; the task only runs when something asks it to."""

    describe = "manual"

    async def fires(self, cancel: asyncio.Event) -> AsyncIterator[Firing]:
        await cancel.wait()
        return
        yield  # pragma: no cover


def _next_tick(tick: int, elapsed: float, every: float) -> int:
    """Which tick to aim at next, having just fired ``tick``.

    Anchored to a grid rather than to when the last run ended, so a run that
    overran does not shift every later tick -- the ticks it ate are skipped
    rather than queued, which is why a card that took an hour does not then
    fire sixty times in a row.

    **Always at least one later.** A timer that woke a hair early leaves
    ``elapsed`` still inside the period just fired, so ``elapsed // every``
    names that same tick again -- and the delay to a tick already past is
    zero, which fires immediately and turns one period into two. Windows'
    clock is coarse enough to do this routinely.

    A function rather than two lines in the loop because that invariant is
    arithmetic, and the test that used to guard it measured wall-clock gaps
    instead: on a loaded runner a starved loop records one timestamp late and
    the next on time, so the gap between them shrinks whatever the timer did.
    It cannot tell a correct trigger from a broken one, and it failed CI
    saying so.
    """
    return max(tick + 1, int(elapsed // every) + 1)


class IntervalTrigger(Trigger):
    """Fires every N seconds on an absolute grid, skipping ticks a slow run ate."""

    def __init__(
        self,
        every: float,
        jitter: float = 0.0,
        run_at_start: bool = True,
        max_iterations: int | None = None,
    ):
        super().__init__(max_iterations)
        if every <= 0:
            raise SpecError("interval trigger 'every' must be positive")
        self.every = every
        self.jitter = max(0.0, jitter)
        self.run_at_start = run_at_start
        self.describe = f"every {humanize(every)}"

    async def fires(self, cancel: asyncio.Event) -> AsyncIterator[Firing]:
        loop = asyncio.get_running_loop()
        origin = loop.time()
        iteration = 0
        tick = 0

        if not self.run_at_start:
            if not await _sleep_or_cancel(self.every, cancel):
                return

        while not cancel.is_set():
            iteration += 1
            if self._exhausted(iteration):
                return
            yield Firing(iteration=iteration, at=datetime.now(), reason=self.describe)
            if self._exhausted(iteration + 1):
                return  # nothing left to fire; do not sit out the period

            tick = _next_tick(tick, loop.time() - origin, self.every)
            delay = origin + tick * self.every - loop.time()
            if self.jitter:
                delay += random.uniform(0, self.jitter)
            if not await _sleep_or_cancel(delay, cancel):
                return


class CronTrigger(Trigger):
    """Fires on a cron schedule, evaluated in local time."""

    def __init__(self, schedule: CronSchedule, max_iterations: int | None = None):
        super().__init__(max_iterations)
        self.schedule = schedule
        self.describe = f"cron {schedule.expression}"

    async def fires(self, cancel: asyncio.Event) -> AsyncIterator[Firing]:
        iteration = 0
        while not cancel.is_set():
            if self._exhausted(iteration + 1):
                return
            now = datetime.now()
            target = self.schedule.next_after(now)
            if not await _sleep_or_cancel((target - now).total_seconds(), cancel):
                return
            iteration += 1
            yield Firing(iteration=iteration, at=target, reason=self.describe)


class LoopTrigger(Trigger):
    """Runs the graph back to back forever, pausing only for ``cooldown``.

    Iterations never overlap; a slow model simply slows the loop down.
    """

    def __init__(self, cooldown: float = 0.0, max_iterations: int | None = None):
        super().__init__(max_iterations)
        self.cooldown = max(0.0, cooldown)
        self.describe = f"loop (cooldown {cooldown:g}s)" if cooldown else "loop"

    async def fires(self, cancel: asyncio.Event) -> AsyncIterator[Firing]:
        iteration = 0
        while not cancel.is_set():
            iteration += 1
            if self._exhausted(iteration):
                return
            yield Firing(iteration=iteration, at=datetime.now(), reason="loop")
            if self._exhausted(iteration + 1):
                return
            if not await _sleep_or_cancel(self.cooldown, cancel):
                return
