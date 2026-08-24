"""How worn each connection is: runtime emphasis, never meaning.

What connects to what stays a judgment in markdown; this file holds only
how often a connection actually helped, and it is built so it cannot run
away: every weight decays by age (a half-life, applied whenever it is
read), and no entry's total can exceed the fan cap -- an entry connected to
everything has weak claims on each.

Deleting `.poieo/strength.json` loses which paths were worn, and nothing
else; the project relearns them by working. Accordingly, nothing in here is
ever worth failing anything over: corrupt reads as empty, failed writes are
logged and swallowed.

Spec: docs/superpowers/specs/2026-08-24-worn-paths-design.md
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger("poieo.memory")

FILE_NAME = "strength.json"
# One reinforcement is worth 1.0 and halves every HALF_LIFE days untouched.
HALF_LIFE_DAYS = 30.0
# The most total wear one entry's connections may carry (the fan effect).
FAN_CAP = 10.0
# Below this a pair is noise and is dropped on the next write.
_FLOOR = 0.01
# A pair counts as worn -- enough to carry a second hop -- at this level:
# one fresh reinforcement stays worn for one half-life.
WORN_FLOOR = 0.5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _path(project_dir: Path) -> Path:
    return Path(project_dir) / ".poieo" / FILE_NAME


def _decayed(weight: float, since: str, now: datetime) -> float:
    try:
        age = (now - datetime.fromisoformat(since)).total_seconds()
    except ValueError:
        return 0.0
    return weight * 0.5 ** (max(age, 0.0) / (HALF_LIFE_DAYS * 86400))


def _read(project_dir: Path, now: datetime) -> dict[str, float]:
    path = _path(project_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        pairs = raw.get("pairs", {}) if isinstance(raw, dict) else {}
        return {
            key: value
            for key, entry in pairs.items()
            if isinstance(entry, dict)
            and (value := _decayed(float(entry.get("w", 0)), str(entry.get("at", "")), now))
            > _FLOOR
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("could not read %s (%s); treating it as empty", path, exc)
        return {}


def wear_of(
    project_dir: Path, now: datetime | None = None
) -> dict[frozenset[str], float]:
    """Current wear, decayed as of now. Pairs naming entries that no longer
    exist are the caller's to ignore -- this file knows names, not files."""
    now = now or _now()
    return {
        frozenset(key.split("|", 1)): value
        for key, value in _read(project_dir, now).items()
        if "|" in key
    }


def wear(
    project_dir: Path, pairs: Iterable[tuple[str, str]], now: datetime | None = None
) -> None:
    """Reinforce each pair by one. Decay lands first, the fan cap after,
    and nothing that goes wrong here may reach the caller."""
    now = now or _now()
    try:
        weights = _read(project_dir, now)
        for a, b in pairs:
            if a == b:
                continue
            key = "|".join(sorted((a, b)))
            weights[key] = weights.get(key, 0.0) + 1.0

        # The fan effect: scale every pair by the tightest cap either of its
        # entries demands, so no entry's total exceeds FAN_CAP.
        totals: dict[str, float] = {}
        for key, value in weights.items():
            for name in key.split("|", 1):
                totals[name] = totals.get(name, 0.0) + value
        scaled = {}
        for key, value in weights.items():
            factor = min(
                (FAN_CAP / totals[name] for name in key.split("|", 1) if totals[name] > FAN_CAP),
                default=1.0,
            )
            if value * factor > _FLOOR:
                scaled[key] = value * factor

        path = _path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = now.isoformat(timespec="seconds")
        body = json.dumps(
            {"pairs": {key: {"w": round(value, 6), "at": stamp} for key, value in scaled.items()}},
            ensure_ascii=False,
            indent=1,
        )
        temp = path.with_suffix(".json.tmp")
        temp.write_text(body, encoding="utf-8")
        os.replace(temp, path)
    except Exception as exc:
        log.warning("could not record the wear in %s: %s", project_dir, exc)
