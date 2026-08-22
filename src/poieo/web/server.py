"""Read-only observation API served from inside the daemon.

Everything here answers "what is happening / what happened" -- no route
mutates anything. Control endpoints belong to the next roadmap slice.
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


def _checkpoint_for(daemon: Any, flow: str | None) -> Any:
    """The private copy behind a flow, if it keeps one."""
    for runner in daemon.runners:
        if runner.name == flow:
            return getattr(runner, "checkpoint", None)
    return None


def create_app(daemon: Any) -> Starlette:
    """Build the app over a daemon-shaped object (.runners, .store)."""

    def flows(request: Request) -> JSONResponse:
        rows = []
        for runner in daemon.runners:
            last = runner.last_result
            rows.append(
                {
                    "name": runner.name,
                    "graph": runner.flow.graph.name,
                    "trigger": runner.trigger.describe,
                    "status": runner.status,
                    "current_run_id": runner.current_run_id,
                    "last_run": last.summary() if last else None,
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
        summary = daemon.store.run(run_id)
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
            return FileResponse(page)
        return PlainTextResponse(
            "poieo web UI is not built yet. The API is live: /api/flows"
        )

    routes = [
        Route("/api/flows", flows),
        Route("/api/runs", runs),
        Route("/api/runs/{run_id}", run_detail),
        Route("/api/runs/{run_id}/diff", run_diff),
        Route("/api/events", events),
        Route("/", index),
    ]
    if STATIC_DIR.is_dir():
        routes.append(Mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets"))
    return Starlette(routes=routes)
