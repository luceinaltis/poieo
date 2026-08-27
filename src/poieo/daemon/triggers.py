"""Triggers decide *when* a task fires; the daemon decides what happens then.

Each is an async generator that yields a :class:`Firing` and **only resumes once
the run has finished** -- which is what makes ``loop`` a true "run
continuously" mode instead of a queue piling up behind a slow model.

Design: docs/daemon.md
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..errors import SpecError
from .cron import CronSchedule

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)?\s*$", re.IGNORECASE)
_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def parse_duration(value: str | int | float) -> float:
    """``"30s"`` / ``"5m"`` / ``90`` -> seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    match = _DURATION.match(str(value))
    if not match:
        raise SpecError(f"cannot parse duration {value!r} (try '30s', '5m', '2h')")
    amount, unit = match.groups()
    return float(amount) * _UNITS[(unit or "s").lower()]


def humanize(seconds: float) -> str:
    """Seconds back in the units somebody would have written them in.

    The inverse of :func:`parse_duration`, near enough: `30m` read back as
    `every 1800s` makes a person do arithmetic to check their own config, and
    only one of those two can be checked at a glance. The largest unit that
    divides evenly wins; nothing does, and seconds is the honest answer.

    This reaches further than it looks -- it is what `poieo tasks`, `flows`
    and `validate` print, what the board labels a task with, and the reason
    every interval run records for having fired.
    """
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size and seconds % size == 0:
            return f"{seconds / size:g}{unit}"
    return f"{seconds:g}s"


@dataclass(slots=True)
class Firing:
    """One scheduled activation of a task."""

    iteration: int
    at: datetime
    reason: str


class TriggerSpec(BaseModel):
    """Declarative trigger configuration, discriminated by ``type``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["manual", "interval", "cron", "loop"] = "manual"

    # interval
    every: str | float | None = None
    jitter: str | float = 0
    run_at_start: bool = True

    # cron
    expression: str | None = None

    # loop
    cooldown: str | float = 0

    # all types
    max_iterations: int | None = Field(default=None, ge=1)

    @field_validator("expression")
    @classmethod
    def _valid_cron(cls, value: str | None) -> str | None:
        if value is not None:
            CronSchedule(value)
        return value

    @field_validator("every", "jitter", "cooldown")
    @classmethod
    def _valid_duration(cls, value: str | float | None) -> str | float | None:
        # Checked here, not in build(): a schedule that cannot parse must
        # fail where `poieo validate` and the daemon's load can see it,
        # not when the trigger is first armed.
        if value is not None:
            parse_duration(value)
        return value

    def build(self) -> Trigger:
        if self.type == "interval":
            if self.every is None:
                raise SpecError("interval trigger requires 'every'")
            return IntervalTrigger(
                every=parse_duration(self.every),
                jitter=parse_duration(self.jitter),
                run_at_start=self.run_at_start,
                max_iterations=self.max_iterations,
            )
        if self.type == "cron":
            if not self.expression:
                raise SpecError("cron trigger requires 'expression'")
            return CronTrigger(
                schedule=CronSchedule(self.expression),
                max_iterations=self.max_iterations,
            )
        if self.type == "loop":
            return LoopTrigger(
                cooldown=parse_duration(self.cooldown),
                max_iterations=self.max_iterations,
            )
        return ManualTrigger(max_iterations=self.max_iterations)


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

            # Anchored to the grid, so a run that overran does not shift every
            # later tick and elapsed ticks are skipped rather than queued.
            # Always advance by at least one: a timer that woke a hair early
            # (Windows' clock is coarse) would otherwise refire the same tick.
            elapsed = loop.time() - origin
            tick = max(tick + 1, int(elapsed // self.every) + 1)
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
