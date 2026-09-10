"""Undo a recorded application through the same checks as new work.

Design: docs/daemon.md
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..card import append_journal, load_card
from ..errors import PoieoError
from ..memory import write_result
from ..memory.results import revise_application
from ..runtime import RunResult, new_run_id
from ..store import Event, utcnow
from .changes import check_and_apply


async def undo_change(driver: Any, run_id: str) -> dict:
    row = driver.store.summary(run_id)
    if not row or row.get("task") != driver.name or row.get("project") != driver.config.display_name:
        return {"status": "blocked", "error": "this run is missing or belongs to another task"}
    applied = row.get("application") or {}
    if applied.get("status") != "applied" or not applied.get("before") or not applied.get("after"):
        return {"status": "blocked", "error": "this run has no applied change to undo"}
    if applied.get("undo_of"):
        return {"status": "blocked", "error": "this run already records an undo"}
    card = driver.config.cards_by_task.get(driver.name)
    policy = load_card(card.source_path).apply if card and card.source_path else driver.task.spec.apply
    undo_id, started = new_run_id(), utcnow()
    driver.store.append(
        Event(
            run_id=undo_id,
            type="run_started",
            data={
                "task": driver.name,
                "project": driver.config.display_name,
                "graph": driver.task.graph.name,
                "trigger": f"undo change from {run_id}",
            },
        )
    )
    try:
        outcome = await check_and_apply(
            driver.workspace,
            policy,
            manual=True,
            tool_context=driver.tool_context,
            undo=(applied["before"], applied["after"], undo_id),
        )
    except PoieoError as exc:
        outcome = {"status": "blocked", "error": str(exc)}
    outcome.update(run_id=undo_id, undo_of=run_id)
    result = RunResult(
        run_id=undo_id,
        task=driver.name,
        graph=driver.task.graph.name,
        status="completed" if outcome["status"] == "applied" else "failed",
        started_at=started,
        finished_at=utcnow(),
        steps=0,
        path=["undo"],
        usage={},
        outputs={
            "undo": "Undid the applied changes" if outcome["status"] == "applied" else "The change could not be undone"
        },
        state={},
        project=driver.config.display_name,
        trigger=f"undo change from {run_id}",
        application=outcome,
        error=outcome.get("error"),
    )
    if outcome["status"] == "applied":
        report = await asyncio.to_thread(driver.workspace.diff, outcome["before"], outcome["after"])
        result.change = {
            "base": report["base"],
            "head": report["head"],
            "files": [file["path"] for file in report["files"]],
            "insertions": sum(file["insertions"] for file in report["files"]),
            "deletions": sum(file["deletions"] for file in report["files"]),
            "message": result.said(),
        }
        driver.pause()
        for affected in dict.fromkeys([run_id, *applied.get("run_ids", [])]):
            old = driver.store.summary(affected)
            previous = (old or {}).get("application") or {}
            if not old or old.get("task") != driver.name or old.get("project") != driver.config.display_name:
                continue
            if (previous.get("before"), previous.get("after")) != (applied["before"], applied["after"]):
                continue
            revised = {
                **previous,
                "status": "undone",
                "undo": {
                    "run_id": undo_id,
                    "before": outcome["before"],
                    "after": outcome["after"],
                },
            }
            driver.store.append(Event(run_id=affected, type="run_application", data=revised))
            driver.store.record_summary({**old, "application": revised})
            for known in driver.results:
                if known.run_id == affected:
                    known.application = revised
            if card:
                revise_application(card, affected, revised)
    driver.results.append(result)
    driver.store.append(Event(run_id=undo_id, type="run_application", data=outcome))
    driver.store.record_summary(result.summary())
    if card:
        write_result(card, result)
        try:
            append_journal(card.journal_path(), "change", result.said(), title=card.name)
        except OSError:
            pass  # The durable run remains available if its journal is unwritable.
    return outcome
