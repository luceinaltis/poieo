"""One bounded run to reconcile a task's work with the current project.

Design: docs/daemon.md
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from ..expr import render, wrap
from ..graph import GraphSpec, NodeSpec, OutputSpec
from ..runtime import RunResult
from ..runtime.executor import execute
from ..workspace import PreparedChange, WorkspaceError
from .changes import finish_write


async def repair_change(
    driver: Any,
    parent: RunResult,
    prepared: PreparedChange,
    failure: dict,
    records: list[RunResult],
    cancel: asyncio.Event,
) -> dict:
    """Reuse an executed file worker's permission; do not repeat the workflow."""
    if driver._over_budget(additional_cost=parent.usage.get("cost") or 0):
        return {"ready": False, "reason": "The project has reached its spending limit."}
    workers = {node.id: node for node in driver.task.graph.nodes if node.type == "agent"}
    source = next(
        (
            workers[name]
            for name in reversed(parent.path)
            if name in workers and set(workers[name].tools or []) & {"files", "shell"}
        ),
        None,
    )
    if source is None:
        return {"ready": False, "reason": "This task has no file worker available to repair the change."}
    payload = driver._run_input
    scope = {
        "input": wrap(payload),
        "state": wrap(parent.state),
        "nodes": wrap(parent.outputs),
        "run": wrap({"id": parent.run_id, "task": parent.task}),
        **{name: wrap(value) for name, value in parent.aliases.items()},
    }
    system = render(source.system or "", scope)
    repair_input = {
        "original_input": payload,
        "original_work": driver.task.graph.model_dump(exclude={"source_path"}),
        "original_result": parent.outputs,
        "failure": failure,
        "allowed_paths": driver.task.spec.apply.paths or ["."],
    }
    node = NodeSpec(
        id="repair",
        type="agent",
        role=source.role,
        params=source.params,
        system="{{ input.original_system }}\n"
        "Repair only this task's file change in the supplied private copy. Preserve the latest project work "
        "and the original task's intent. Resolve compatible overlap or fix the failed check. Do not repeat "
        "external actions, change verification rules, commit, switch branches, or broaden permission. "
        "If the goals contradict each other, stop and explain the decision needed. "
        'Finish with JSON: {"decision":"ready" or "needs_decision","summary":"what changed or why you stopped"}.',
        prompt="Reconcile this work with the current project:\n{{ input.repair }}",
        tools=[name for name in source.tools or [] if name in {"files", "shell"}],
        max_turns=min(source.max_turns, 8),
        deadline=min(source.deadline or 180, 180),
        output=OutputSpec(format="json"),
    )
    graph = GraphSpec(
        name=driver.task.graph.name, entry=node.id, nodes=[node], default_role=driver.task.graph.default_role
    )
    context = replace(driver.tool_context, containers=None) if driver.tool_context else None
    result = await execute(
        graph,
        driver.task.binding,
        driver.pool,
        driver.store,
        input={"original_system": system, "repair": repair_input},
        task=driver.name,
        project=driver.config.display_name,
        trigger=f"repair change from {parent.run_id}",
        cancel=cancel,
        workdir=await asyncio.to_thread(driver.workspace.check_folder, prepared),
        tool_context=context,
    )
    records.append(result)
    answer = result.outputs.get("repair")
    ready = (
        result.status == "completed"
        and not cancel.is_set()
        and isinstance(answer, dict)
        and answer.get("decision") == "ready"
    )
    reason = answer.get("summary") if isinstance(answer, dict) else result.error
    if isinstance(answer, dict):
        result.outputs["repair"] = str(answer.get("summary") or "Repair finished")
        result.outputs["decision"] = answer.get("decision")
    if ready:
        try:
            change = await finish_write(
                asyncio.to_thread(
                    driver.workspace.save_repair, prepared, result.run_id, result.said("Repair task change")
                )
            )
            if change:
                result.change = change.as_dict()
        except (WorkspaceError, OSError) as exc:
            ready, reason = False, str(exc)
    return {"ready": ready, "run_id": result.run_id, "reason": reason or "The repair could not finish."}
