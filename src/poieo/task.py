"""The full form of a task: what runs, on what schedule, against which binding.

A task file written by hand and a card that ``expand`` desugars both end up as
one of these, and the daemon and ``poieo run`` both load it. It is the shape
the two sides agree on, so it sits below both: this module knows nothing about
cards, folders of them, or the scheduler that arms a trigger.

The schedule settings and their notation -- ``"5m"``, a cron expression -- are
here for the same reason. A card has to say when it runs without reaching into
the daemon, and a schedule that cannot parse must fail where ``poieo validate``
and the daemon's load can see it, not when the trigger is first armed.

Design: docs/tasks.md
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cron import CronSchedule
from .errors import SpecError
from .graph import Branch
from .tools import Isolation
from .workspace import ApplySpec

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


class TriggerSpec(BaseModel):
    """Declarative trigger configuration, discriminated by ``type``.

    Settings only: the daemon's ``build_trigger`` turns one into the trigger
    that actually waits, which is why nothing here knows what a trigger does.
    """

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
        # Checked here, not when the trigger is built: a schedule that cannot
        # parse must fail where `poieo validate` and the daemon's load can see
        # it, not when the trigger is first armed.
        if value is not None:
            parse_duration(value)
        return value


class TaskSpec(BaseModel):
    """One logical workflow wired to a trigger and a binding."""

    model_config = ConfigDict(extra="forbid")

    name: str
    graph: str
    # Falls back to the daemon-level binding when omitted.
    binding: str | None = None
    trigger: TriggerSpec = Field(default_factory=TriggerSpec)
    enabled: bool = True

    # Where this task's agent nodes work. Resolved against the config file, so
    # the graph can stay portable and say nothing about this machine.
    workdir: str | None = None

    # Static payload handed to every run.
    input: dict[str, Any] = Field(default_factory=dict)
    # Re-read before each run, so an external process can feed the task.
    input_file: str | None = None
    # Carry the ending state of one run into the next -- the memory that makes
    # a looping task accumulate instead of restarting from zero every time.
    carry_state: bool = False
    # Where this task's commands may run. Absent means the host, as before.
    isolation: Isolation | None = None
    apply: ApplySpec = Field(default_factory=ApplySpec)
    on_error: Literal["continue", "stop"] = "continue"

    # Which task should work next: the router's own when/to/label, one level
    # up. First match wins, and `to: null` means matched-and-no-further. No
    # `default`, because a finished run does not have to go anywhere; a
    # catch-all is a last branch reading `"true"`.
    then: list[Branch] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_name(self) -> TaskSpec:
        if not self.name.strip():
            raise ValueError("task name must not be empty")
        return self
