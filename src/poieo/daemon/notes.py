"""Keep direction durable until it can be read by the next run.

Design: docs/tasks.md
"""

import json
import logging
import os
import time
from typing import Any

from ..card import append_journal
from ..errors import SpecError
from ..runtime import new_run_id

log = logging.getLogger("poieo.daemon")


def leave_note(driver: Any, text: str) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise SpecError("write between 1 and 4000 characters of direction")
    card = driver.config.cards_by_task.get(driver.name)
    if card is None:
        raise SpecError("this task has no card to keep direction with")
    folder = driver.config.layout().notes(card.slug)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.time_ns()}-{new_run_id()}.json"
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump({"text": text.strip()}, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    if not driver._change_lock.locked():
        deliver_notes(driver)
    return {"status": "saved"}


def deliver_notes(driver: Any) -> None:
    card = driver.config.cards_by_task.get(driver.name)
    if card is None:
        return
    for path in sorted(driver.config.layout().notes(card.slug).glob("*.json")):
        try:
            text = json.loads(path.read_text(encoding="utf-8"))["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("direction is empty")
            append_journal(card.journal_path(), "you", text, title=card.name)
            # Append before removing: a crash may repeat a note, never lose it.
            path.unlink()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("task '%s': queued direction could not be delivered: %s", driver.name, exc)
