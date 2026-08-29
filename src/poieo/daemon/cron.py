"""A dependency-free 5-field cron parser.

Supports the fields ``minute hour day-of-month month day-of-week`` with ``*``,
``*/step``, ``a-b``, ``a-b/step``, comma lists, and three-letter month/day names.
Day-of-month and day-of-week follow the usual cron rule: when *both* are
restricted, a day matching *either* one fires.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..errors import SpecError

_MONTHS = {n: i for i, n in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
_DAYS = {n: i for i, n in enumerate("sun mon tue wed thu fri sat".split())}

_FIELDS = (
    ("minute", 0, 59, {}),
    ("hour", 0, 23, {}),
    ("day", 1, 31, {}),
    ("month", 1, 12, _MONTHS),
    ("weekday", 0, 6, _DAYS),
)

# Four years covers every leap-day schedule without looping forever on one
# that can never fire (e.g. "0 0 30 2 *").
_MAX_DAYS_AHEAD = 366 * 4


def _parse_field(raw: str, name: str, low: int, high: int, names: dict[str, int]) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip().lower()
        if not part:
            raise SpecError(f"cron {name}: empty item in {raw!r}")

        step = 1
        if "/" in part:
            part, _, step_raw = part.partition("/")
            if not step_raw.isdigit() or int(step_raw) == 0:
                raise SpecError(f"cron {name}: bad step {step_raw!r}")
            step = int(step_raw)

        if part in ("*", ""):
            start, end = low, high
        elif "-" in part.lstrip("-"):
            start_raw, _, end_raw = part.partition("-")
            start = _to_int(start_raw, name, names)
            end = _to_int(end_raw, name, names)
        else:
            start = end = _to_int(part, name, names)

        if name == "weekday":
            # Both 0 and 7 mean Sunday in cron.
            start, end = (0 if start == 7 else start), (0 if end == 7 else end)
        if not (low <= start <= high and low <= end <= high) or start > end:
            raise SpecError(f"cron {name}: {part!r} is out of range {low}-{high}")
        values.update(range(start, end + 1, step))
    return values


def _to_int(token: str, field: str, names: dict[str, int]) -> int:
    token = token.strip().lower()
    if token in names:
        return names[token]
    if token.isdigit():
        return int(token)
    raise SpecError(f"cron {field}: cannot parse {token!r}")


class CronSchedule:
    """A parsed cron expression, resolved at minute granularity in local time."""

    def __init__(self, expression: str):
        self.expression = expression.strip()
        parts = self.expression.split()
        if len(parts) != 5:
            raise SpecError(
                f"cron expression {expression!r} must have 5 fields (minute hour day month weekday), got {len(parts)}"
            )
        self.minutes, self.hours, self.days, self.months, self.weekdays = (
            _parse_field(raw, name, low, high, names) for raw, (name, low, high, names) in zip(parts, _FIELDS)
        )
        self._day_restricted = parts[2].strip() != "*"
        self._weekday_restricted = parts[4].strip() != "*"

    def _day_matches(self, moment: datetime) -> bool:
        if moment.month not in self.months:
            return False
        # Python's weekday() is Monday=0; cron counts Sunday=0.
        weekday = (moment.weekday() + 1) % 7
        dom_ok = moment.day in self.days
        dow_ok = weekday in self.weekdays
        if self._day_restricted and self._weekday_restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def matches(self, moment: datetime) -> bool:
        return moment.minute in self.minutes and moment.hour in self.hours and self._day_matches(moment)

    def next_after(self, after: datetime) -> datetime:
        """The first matching minute strictly after ``after``."""
        candidate = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
        days_scanned = 0
        while days_scanned <= _MAX_DAYS_AHEAD:
            if not self._day_matches(candidate):
                candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
                days_scanned += 1
                continue
            if candidate.hour not in self.hours:
                nxt = candidate + timedelta(hours=1)
                candidate = nxt.replace(minute=0)
                if candidate.date() != nxt.date() or candidate.hour == 0:
                    days_scanned += 1
                continue
            if candidate.minute not in self.minutes:
                candidate += timedelta(minutes=1)
                if candidate.minute == 0:
                    # Rolled into a new hour (possibly a new day); re-check above.
                    if candidate.hour == 0:
                        days_scanned += 1
                continue
            return candidate
        raise SpecError(f"cron expression {self.expression!r} will never fire")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CronSchedule({self.expression!r})"
