"""The graph walker.

Execution is a loop, not a topological sort: a node names its successor, and a
router picks between successors at run time. Cycles are allowed on purpose --
that is how a graph "keeps going" -- and ``graph.max_steps`` bounds them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..binding import BindingSpec
from ..errors import BindingError, Cause, PoieoError, RunAborted, SpecError, explain_failure
from ..expr import unwrap
from ..graph import GraphSpec
from ..providers import ProviderPool
from ..store import RunStore, utcnow
from ..tools import ToolContext
from .context import RunContext, RunResult, new_run_id
from .nodes import build_node


def needs_a_workdir(graph: GraphSpec) -> list[str]:
    """Agent nodes that will have to be told where to work."""
    return [n.id for n in graph.nodes if n.type == "agent" and not n.workdir]


def preflight(
    graph: GraphSpec,
    binding: BindingSpec,
    *,
    workdir: Path | None = None,
    require_workdir: bool = True,
) -> None:
    """Fail before spending tokens if the run cannot possibly succeed.

    ``require_workdir=False`` is for checking a graph on its own, where not
    naming a directory is the point rather than a defect.
    """
    missing = binding.check_roles(graph.roles())
    if missing:
        raise BindingError(
            f"binding '{binding.name}' cannot resolve role(s) "
            f"{missing} required by graph '{graph.name}'"
        )
    if require_workdir and workdir is None:
        homeless = needs_a_workdir(graph)
        if homeless:
            raise SpecError(
                f"agent node(s) {homeless} in graph '{graph.name}' have nowhere to "
                f"work: give the node a workdir, or the flow one"
            )


async def execute(
    graph: GraphSpec,
    binding: BindingSpec,
    pool: ProviderPool,
    store: RunStore,
    *,
    input: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    flow: str = "adhoc",
    trigger: str = "manual",
    iteration: int = 0,
    run_id: str | None = None,
    cancel: asyncio.Event | None = None,
    workdir: Path | None = None,
    tool_context: ToolContext | None = None,
    finalize: Callable[[RunResult], Awaitable[None]] | None = None,
) -> RunResult:
    """Run ``graph`` once and return the outcome.

    Never raises for an in-run failure: the error is captured on the result so a
    daemon flow can log it and stay up. Spec/binding problems still raise, since
    those mean the flow is misconfigured rather than flaky.
    """
    preflight(graph, binding, workdir=workdir)

    ctx = RunContext(
        graph=graph,
        binding=binding,
        pool=pool,
        store=store,
        run_id=run_id or new_run_id(),
        flow=flow,
        trigger=trigger,
        input=dict(input or {}),
        state={**graph.state, **(state or {})},
        iteration=iteration,
        cancel=cancel,
        workdir=workdir,
        tool_context=tool_context,
    )

    started_at = utcnow()
    ctx.emit(
        "run_started",
        graph=graph.name,
        flow=flow,
        trigger=trigger,
        iteration=iteration,
        binding=binding.name,
        input=unwrap(ctx.input),
    )

    status = "completed"
    error: str | None = None
    cause: Cause | None = None
    current: str | None = graph.entry
    steps = 0

    try:
        while current is not None:
            if cancel is not None and cancel.is_set():
                raise RunAborted("cancelled before completing the graph")
            if steps >= graph.max_steps:
                raise RunAborted(
                    f"exceeded max_steps ({graph.max_steps}); the graph may be "
                    f"cycling without an exit condition"
                )

            spec = graph.node(current)
            steps += 1
            ctx.path.append(current)
            ctx.emit("node_started", node_id=current, type=spec.type, step=steps)

            result = await build_node(spec).run(ctx)

            ctx.emit(
                "node_finished",
                node_id=current,
                step=steps,
                next=result.next_node,
                output=unwrap(result.output),
                **result.meta,
            )
            current = result.next_node
    except RunAborted as exc:
        status, error = "aborted", str(exc)
        cause = explain_failure(exc)
        ctx.emit("run_aborted", reason=error,
                 **({"cause": cause.as_dict()} if cause else {}))
    except PoieoError as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        # Classified here, at the one place the original exception still
        # exists -- everything downstream sees only strings.
        cause = explain_failure(exc)
        ctx.emit("run_failed", node_id=getattr(exc, "node_id", None), error=error,
                 **({"cause": cause.as_dict()} if cause else {}))
    except asyncio.CancelledError:
        ctx.emit("run_aborted", reason="cancelled")
        raise

    finished_at = utcnow()
    run_result = RunResult(
        run_id=ctx.run_id,
        flow=flow,
        graph=graph.name,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        steps=steps,
        path=list(ctx.path),
        usage=ctx.usage.as_dict(),
        outputs=unwrap(ctx.outputs),
        state=unwrap(ctx.state),
        trigger=trigger,
        error=error,
        cause=cause.as_dict() if cause else None,
        iteration=iteration,
    )

    if status == "completed":
        ctx.emit(
            "run_finished", steps=steps, usage=ctx.usage.as_dict(), path=list(ctx.path)
        )
    # Last chance to add to the outcome: the summary written next is what the
    # store keeps, and nobody gets to amend it afterwards.
    if finalize is not None:
        await finalize(run_result)
    store.record_summary(run_result.summary())
    return run_result
