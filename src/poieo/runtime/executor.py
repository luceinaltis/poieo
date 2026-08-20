"""The graph walker.

Execution is a loop, not a topological sort: a node names its successor, and a
router picks between successors at run time. Cycles are allowed on purpose --
that is how a graph "keeps going" -- and ``graph.max_steps`` bounds them.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..binding import BindingSpec
from ..errors import BindingError, PoieoError, RunAborted
from ..expr import unwrap
from ..graph import GraphSpec
from ..providers import ProviderPool
from ..store import RunStore, utcnow
from .context import RunContext, RunResult, new_run_id
from .nodes import build_node


def preflight(graph: GraphSpec, binding: BindingSpec) -> None:
    """Fail before spending tokens if the binding cannot serve every role."""
    missing = binding.check_roles(graph.roles())
    if missing:
        raise BindingError(
            f"binding '{binding.name}' cannot resolve role(s) "
            f"{missing} required by graph '{graph.name}'"
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
) -> RunResult:
    """Run ``graph`` once and return the outcome.

    Never raises for an in-run failure: the error is captured on the result so a
    daemon flow can log it and stay up. Spec/binding problems still raise, since
    those mean the flow is misconfigured rather than flaky.
    """
    preflight(graph, binding)

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
        ctx.emit("run_aborted", reason=error)
    except PoieoError as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        ctx.emit("run_failed", node_id=getattr(exc, "node_id", None), error=error)
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
        error=error,
        iteration=iteration,
    )

    if status == "completed":
        ctx.emit(
            "run_finished", steps=steps, usage=ctx.usage.as_dict(), path=list(ctx.path)
        )
    store.record_summary(run_result.summary())
    return run_result
