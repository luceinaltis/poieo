"""The observation and control API served from inside the daemon.

Almost everything here answers "what is happening / what happened". The
routes that change anything come in exactly two kinds, one fence each:

- **The review** -- accept and discard. The moment the user's own files are
  allowed to change, and the only routes that may ever touch them. If you
  are adding a third of these, stop.
- **Control** -- pause, resume, run-now. These touch the daemon's runtime
  state and nothing else: no file, no schedule on disk, nothing that
  survives a restart.

Both kinds are marked again where they are registered.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..errors import BindingError, PoieoError
from .events import BroadcastStore

STATIC_DIR = Path(__file__).parent / "static"


def sse_frame(record: dict[str, Any]) -> str:
    return f"data: {json.dumps(record, ensure_ascii=False)}\n\n"


async def _event_stream(store: BroadcastStore, flow: str | None = None) -> AsyncIterator[str]:
    queue = store.subscribe()
    try:
        while True:
            record = await queue.get()
            if flow:
                run_flow = record.get("flow") or store.run_flows.get(record.get("run_id", ""))
                if run_flow != flow:
                    continue
            yield sse_frame(record)
    finally:
        store.unsubscribe(queue)


class ImmutableFiles(StaticFiles):
    """Static files whose names change whenever their contents do."""

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = "public, max-age=31536000, immutable"
        return response


def _runner_for(daemon: Any, flow: str | None) -> Any:
    for runner in daemon.runners:
        if runner.name == flow:
            return runner
    return None


def _checkpoint_for(daemon: Any, flow: str | None) -> Any:
    """The private copy behind a flow, if it keeps one."""
    runner = _runner_for(daemon, flow)
    return getattr(runner, "checkpoint", None) if runner else None


def _review_state(runner: Any) -> dict[str, Any]:
    """How much is waiting, and what accepting it would add to."""
    point = getattr(runner, "checkpoint", None)
    if point is None:
        return {"pending": 0, "into": None}
    try:
        return {"pending": len(point.pending()), "into": point.into()}
    except PoieoError:
        # A copy we cannot read is not a reason to fail the whole listing.
        return {"pending": 0, "into": None}


def _branches(branches: Any) -> list[dict[str, Any]]:
    """How an arrow is drawn: where it goes, and the word on it.

    One shape for a router's branches and for a flow's `then:`, because they
    are the same `Branch` one level apart -- a view that can draw one can draw
    the other, and the reader learns one arrow rather than two.

    The label falls back to the condition exactly as `RouterNode` does when it
    records which arm it took, so the board and the run record never disagree
    about what to call an arrow.
    """
    return [{"to": branch.to, "label": branch.label or branch.when} for branch in branches]


def _model(flow: Any, node: Any) -> str | None:
    """The model id this node would actually call, or None if it calls none.

    Resolved the way `runtime/nodes.py` resolves it, so the picture cannot
    claim one model and the run make another. `params` are deliberately not
    passed: they layer generation settings onto a role, never a different
    model, and the board is answering "what runs this", not "how".

    A role the binding never declares is not an error here -- `resolve` falls
    back to `default` for any role at all, which is what makes `role: classifer`
    a silent upgrade rather than a crash. The board reports what will really
    run, which is how that typo becomes visible; `load_flows` says why.
    """
    if node.type == "router":
        return None
    role = node.role or flow.graph.default_role
    try:
        return flow.binding.resolve(role).model
    except BindingError:
        # Only a binding with no default to fall back on gets here. A board
        # that cannot name the model is worth more than one that will not
        # paint -- the same call `_review_state` makes.
        return None


def _shape(flow: Any) -> dict[str, Any]:
    """A graph's wiring: enough to draw it, and nothing else.

    Deliberately not the whole GraphSpec, and not the whole binding either.
    Prompts and system messages are long, are of no use to a drawing, and this
    rides on every board paint to every browser watching -- a graph's text is
    exactly the sort of thing a person hides a secret in. From the binding,
    only the bare model id crosses: a provider knows a base_url and the name of
    the variable its key comes from, and a drawing needs neither.

    It takes the flow rather than the graph because a role resolves against a
    binding, the binding hangs off the flow, and the same graph under two flows
    is two different answers.
    """
    graph = flow.graph
    return {
        "entry": graph.entry,
        "nodes": [
            {
                "id": node.id,
                "type": node.type,
                "next": node.next,
                "default": node.default,
                "branches": _branches(node.branches),
                "model": _model(flow, node),
                # Absent rather than null when the editor never placed it: a
                # view that lays out unplaced nodes itself needs to tell the
                # difference between "at the origin" and "nowhere yet".
                **({"ui": {"x": node.ui.x, "y": node.ui.y}} if node.ui else {}),
            }
            for node in graph.nodes
        ],
    }


def create_app(daemon: Any) -> Starlette:
    """Build the app over a daemon-shaped object (.runners, .store)."""

    async def flows(request: Request) -> JSONResponse:
        # Each review state is two git subprocesses; asked one runner at a
        # time, the board's first paint waits for all of them in single file.
        states = await asyncio.gather(
            *(asyncio.to_thread(_review_state, runner) for runner in daemon.runners)
        )
        rows = []
        for runner, state in zip(daemon.runners, states):
            last = runner.last_result
            rows.append(
                {
                    "name": runner.name,
                    "graph": runner.flow.graph.name,
                    "trigger": runner.trigger.describe,
                    "status": runner.status,
                    "current_run_id": runner.current_run_id,
                    "last_run": last.summary() if last else None,
                    **state,
                    # The two halves of the work graph: which flow this one
                    # hands to, and what it walks on the way there.
                    "then": _branches(runner.flow.spec.then),
                    "shape": _shape(runner.flow),
                }
            )
        return JSONResponse({"flows": rows})

    def runs(request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", "20"))
        flow = request.query_params.get("flow")
        return JSONResponse({"runs": daemon.store.list_runs(limit=limit, flow=flow)})

    def run_detail(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        events = list(daemon.store.events(run_id))
        if not events:
            return JSONResponse({"error": f"no run '{run_id}'"}, status_code=404)
        return JSONResponse({"run_id": run_id, "events": events})

    async def run_diff(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        # An index scan, like the git work below: off the loop it shares.
        summary = await asyncio.to_thread(daemon.store.run, run_id)
        if summary is None:
            return JSONResponse({"error": f"no run '{run_id}'"}, status_code=404)

        change = summary.get("change")
        point = _checkpoint_for(daemon, summary.get("flow"))
        if not change or point is None:
            # A run that altered nothing has nothing to review. That is an
            # answer, not a failure.
            return JSONResponse({"run_id": run_id, "change": None})

        report = await asyncio.to_thread(point.diff, change["base"], change["head"])
        return JSONResponse({"run_id": run_id, **report})

    async def _decide(request: Request, action: str, key: str) -> JSONResponse:
        """accept and discard differ only in which verb and which run id."""
        flow = request.path_params["flow"]
        runner = _runner_for(daemon, flow)
        if runner is None:
            return JSONResponse({"error": f"no flow '{flow}'"}, status_code=404)

        point = getattr(runner, "checkpoint", None)
        if point is None:
            return JSONResponse(
                {"error": f"flow '{flow}' keeps no reviewable copy"}, status_code=409
            )

        try:
            body = await request.json()
        except Exception:
            body = {}  # an empty body means "all of it"

        run_id = (body or {}).get(key)
        target = None
        if run_id:
            summary = await asyncio.to_thread(daemon.store.run, run_id)
            change = (summary or {}).get("change")
            if not change:
                return JSONResponse(
                    {"error": f"run '{run_id}' has no change"}, status_code=404
                )
            target = change["head"]

        try:
            outcome = await asyncio.to_thread(getattr(point, action), target)
        except PoieoError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)

        refused = "dirty" in outcome or "conflict" in outcome
        return JSONResponse(outcome, status_code=409 if refused else 200)

    async def flow_accept(request: Request) -> JSONResponse:
        return await _decide(request, "accept", "through_run_id")

    async def flow_discard(request: Request) -> JSONResponse:
        return await _decide(request, "discard", "from_run_id")

    def _asked(request: Request) -> tuple[Any, JSONResponse | None]:
        """The runner a control route is about, or the 404 saying there isn't one."""
        flow = request.path_params["flow"]
        runner = _runner_for(daemon, flow)
        if runner is None:
            return None, JSONResponse({"error": f"no flow '{flow}'"}, status_code=404)
        return runner, None

    async def _hold(request: Request, verb: str) -> JSONResponse:
        """pause and resume differ only in which verb; both answer the state."""
        runner, missing = _asked(request)
        if missing is not None:
            return missing
        return JSONResponse({"status": getattr(runner, verb)()})

    async def flow_pause(request: Request) -> JSONResponse:
        return await _hold(request, "pause")

    async def flow_resume(request: Request) -> JSONResponse:
        return await _hold(request, "resume")

    async def flow_run(request: Request) -> JSONResponse:
        # Not folded in with the other two: its refusal is a different answer.
        runner, missing = _asked(request)
        if missing is not None:
            return missing
        if not runner.run_now():
            # Iterations never overlap; the refusal names the run in the way.
            return JSONResponse(
                {"error": "a run is in flight", "run_id": runner.current_run_id},
                status_code=409,
            )
        # "starting", not "running": the runner picks the fire up on the next
        # turn of the shared event loop, after this response is already gone.
        return JSONResponse({"status": "starting"})

    async def events(request: Request) -> StreamingResponse:
        flow = request.query_params.get("flow")
        return StreamingResponse(
            _event_stream(daemon.store, flow),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"},
        )

    def index(request: Request):
        page = STATIC_DIR / "index.html"
        if page.exists():
            # This document names the build. Let a browser cache it and the
            # reader keeps running an old page with no way to find out.
            return FileResponse(page, headers={"cache-control": "no-cache"})
        return PlainTextResponse(
            "poieo web UI is not built yet. The API is live: /api/flows"
        )

    routes = [
        Route("/api/flows", flows),
        Route("/api/runs", runs),
        Route("/api/runs/{run_id}", run_detail),
        Route("/api/runs/{run_id}/diff", run_diff),
        Route("/api/events", events),
        # The review: the only routes that may touch the user's own files.
        # If you are adding a third of these, stop.
        Route("/api/flows/{flow}/accept", flow_accept, methods=["POST"]),
        Route("/api/flows/{flow}/discard", flow_discard, methods=["POST"]),
        # Control: the daemon's runtime state and nothing else.
        Route("/api/flows/{flow}/pause", flow_pause, methods=["POST"]),
        Route("/api/flows/{flow}/resume", flow_resume, methods=["POST"]),
        Route("/api/flows/{flow}/run", flow_run, methods=["POST"]),
        Route("/", index),
    ]
    # Vite emits static/assets/<hashed name> and references it as /assets/...,
    # so the mount points one level in, not at the build root.
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        # Asset names carry a content hash, so they can never go stale.
        routes.append(
            Mount("/assets", ImmutableFiles(directory=assets), name="assets")
        )
    return Starlette(routes=routes)
