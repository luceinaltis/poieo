"""The observation and control API served from inside the daemon.

Almost everything answers "what is happening / what happened". The routes that
change anything come in exactly two kinds, marked again where they are
registered:

- **The review** -- accept and discard, the only routes that may ever touch the
  user's own files. If you are adding a third of these, stop.
- **Control** -- pause, resume, run-now. The daemon's runtime state and nothing
  else: no file, no schedule on disk, nothing that survives a restart.

Design: docs/web.md
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

from ..binding import load_binding
from .. import detect as engines
from ..errors import BindingError, PoieoError
from ..providers import credential_for
from .events import BroadcastStore

STATIC_DIR = Path(__file__).parent / "static"


def sse_frame(record: dict[str, Any]) -> str:
    return f"data: {json.dumps(record, ensure_ascii=False)}\n\n"


async def _event_stream(store: BroadcastStore, task: str | None = None) -> AsyncIterator[str]:
    queue = store.subscribe()
    try:
        while True:
            record = await queue.get()
            if task:
                run_flow = record.get("task") or store.run_tasks.get(record.get("run_id", ""))
                if run_flow != task:
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


def _project_of(runner: Any) -> str:
    return runner.config.display_name


def _question(runner: Any) -> dict[str, Any] | None:
    """The question this task is waiting on, as the board needs to show it."""
    pending = getattr(runner, "asking", lambda: None)()
    if pending is None:
        return None
    asked = pending.asked or {}
    return {
        "run_id": pending.run_id,
        "question": asked.get("question", ""),
        "choices": list(asked.get("choices", [])),
    }


def _runner_for(daemon: Any, project: str | None, task: str | None) -> Any:
    """The one runner a project and a task name between them pick out.

    Both, because every project may have a `chores`. The daemon refuses to
    start two projects answering to one name, which is what makes this pair an
    identity rather than a guess.
    """
    for runner in daemon.runners:
        if runner.name != task:
            continue
        # `None` is not "any project" from a route -- those always name one.
        # It is a run record written before the project was on it, which the
        # user's own history is full of, and refusing to show its diff would
        # be losing something over a field it never had the chance to carry.
        if project is None or _project_of(runner) == project:
            return runner
    return None


def _workspace_for(daemon: Any, project: str | None, task: str | None) -> Any:
    """The private copy behind a task, if it keeps one."""
    runner = _runner_for(daemon, project, task)
    return getattr(runner, "workspace", None) if runner else None


def _project_for(daemon: Any, name: str) -> Any:
    """The one project answering to a name, or None.

    A name is an identity here for the same reason it is on a task: the daemon
    refuses to start two projects that share one.
    """
    for project in daemon.projects:
        if project.config.display_name == name:
            return project
    return None


def _models_of(project: Any) -> Any:
    """The binding this project's models panel is about, or None.

    **The spec already in memory**, taken off any task bound to the project's
    own file -- not a fresh read of that file. The board draws a resolved model
    on every node from that same object, and a panel reading the file instead
    would disagree with the graph three inches to its left the moment anybody
    typed `poieo config use`. One truth per screen; a run re-reads the file and
    moves both together (see daemon.md).

    Falling back to a read is for the project whose every task is disabled or
    bound elsewhere: it still has a binding, and refusing to show it because
    nothing happens to be armed would be the check getting in the way.
    """
    wanted = project.config.default_binding_path()
    if wanted is None:
        return None
    for task in getattr(project, "tasks", ()):
        if task.binding_key == str(wanted):
            return task.binding
    return load_binding(wanted)


def _key_state(name: str, provider: Any) -> bool | None:
    """Whether the variable this endpoint names is set -- never what is in it.

    `None` rather than `False` when it names none: "its SDK resolves its own"
    is a different fact from "the key is missing", and a panel that warned
    about the first would cry wolf on every local endpoint. Asked through
    `credential_for`, so the rule about where a key comes from stays in one
    place and the value never comes back here to be leaked.
    """
    if not provider.api_key_env:
        return None
    try:
        credential_for(name, provider)
    except PoieoError:
        return False
    return True


def _review_state(runner: Any) -> dict[str, Any]:
    """How much is waiting, and what accepting it would add to."""
    point = getattr(runner, "workspace", None)
    if point is None:
        return {"pending": 0, "into": None}
    try:
        return {"pending": len(point.pending()), "into": point.into()}
    except PoieoError:
        # A copy we cannot read is not a reason to fail the whole listing.
        return {"pending": 0, "into": None}


def _branches(branches: Any) -> list[dict[str, Any]]:
    """How an arrow is drawn: where it goes, and the word on it.

    One shape for a router's branches and for a task's `then:` -- they are the
    same `Branch` one level apart. The label falls back to the condition
    exactly as `RouterNode` does, so the board and the run record never
    disagree about what to call an arrow.
    """
    return [{"to": branch.to, "label": branch.label or branch.when} for branch in branches]


def _model(task: Any, node: Any) -> str | None:
    """The model id this node would actually call, or None if it calls none.

    Resolved the way `runtime/nodes.py` resolves it, so the picture cannot
    claim one model and the run make another. `params` are not passed: they
    layer generation settings onto a role, never a different model.

    An undeclared role is not an error here -- it falls back to `default`, and
    reporting what will really run is how `role: classifer` becomes visible.
    """
    if node.type != "agent":
        # A router picks a path and a command runs one; neither calls a model.
        # Asked by type rather than by exclusion, so a node type added later
        # is silent here until somebody decides it should not be.
        return None
    role = node.role or task.graph.default_role
    try:
        return task.binding.resolve(role).model
    except BindingError:
        # Only a binding with no default to fall back on gets here. A board
        # that cannot name the model is worth more than one that will not
        # paint -- the same call `_review_state` makes.
        return None


def _shape(task: Any) -> dict[str, Any]:
    """A graph's wiring: enough to draw it, and nothing else.

    Not the whole GraphSpec, and not the whole binding: this rides on every
    board paint to every browser watching, so a graph's prompts stay home and
    only the bare model id crosses.

    Takes the task rather than the graph because a role resolves against a
    binding, and the binding hangs off the task.
    """
    graph = task.graph
    return {
        "entry": graph.entry,
        "nodes": [
            {
                "id": node.id,
                "type": node.type,
                "next": node.next,
                "default": node.default,
                "branches": _branches(node.branches),
                "model": _model(task, node),
                # Which of a task's steps can reach the folder. Two agent nodes
                # are otherwise the same picture -- same type, same model, same
                # box -- and one of them rewrites the project while the other
                # only answers, so a board without this asks the reader to
                # guess at the one thing they cannot afford to.
                #
                # A list, never absent: `None` and `[]` both mean no hands, and
                # a field a view can forget to read is one whose absence draws
                # every step as harmless. Toolset names come from a fixed table
                # and are not the author's prose, unlike the prompts above.
                "tools": list(node.tools or []),
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

    async def tasks(request: Request) -> JSONResponse:
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
                    # Which project's. A name alone stopped being an identity
                    # when one daemon could run several: every project has a
                    # `chores`, and the pair is what a control route takes.
                    "project": _project_of(runner),
                    "graph": runner.task.graph.name,
                    "trigger": runner.trigger.describe,
                    "status": runner.status,
                    "current_run_id": runner.current_run_id,
                    "last_run": last.summary() if last else None,
                    **state,
                    # The two halves of the work graph: which task this one
                    # hands to, and what it walks on the way there.
                    # What it is waiting to be told, if anything. Without
                    # this the answer route is a button with no label on it.
                    "asking": _question(runner),
                    "then": _branches(runner.task.spec.then),
                    "shape": _shape(runner.task),
                }
            )
        # Whose board this is -- all of them. Two daemons on two ports serve
        # pages that are otherwise identical, and the listing with no tasks on
        # it, the one a reader can recognise least, needs saying most; so it
        # rides on the response rather than on each row, and it is a list
        # because a daemon runs as many projects as it was given.
        return JSONResponse(
            {
                "projects": [
                    {
                        "name": project.config.display_name,
                        "root": str(project.config.base_dir),
                    }
                    for project in daemon.projects
                ],
                "tasks": rows,
            }
        )

    async def project_models(request: Request) -> JSONResponse:
        """Every model this project can reach, endpoint by endpoint.

        **Asked live**, for the reason `poieo config models` is: a catalogue
        written down a month ago is a catalogue that has since gone wrong, and
        a model named from memory fails at 3am. Every endpoint is asked at
        once -- two asked in single file is two timeouts on a laptop where
        neither is running.

        What each model carries is whatever its endpoint said about it and
        nothing else. `docs/runtime.md` refuses a price table in this
        repository; this does not add one, it reports the rates an endpoint
        publishes on the same listing it publishes ids on, and leaves a blank
        where none is published rather than guessing at a number.

        Two things deliberately do not cross. A **key** never does -- only the
        name of the variable it comes from, and whether that is set, which is
        usually the whole explanation for an endpoint that listed nothing. Nor
        does a `base_url`: the endpoint's own name tells one from another, and
        an address is the one field in a binding that can carry a private host.
        """
        name = request.path_params["project"]
        project = _project_for(daemon, name)
        if project is None:
            # The board remembers a project across restarts, so a picker
            # holding one the daemon was started without is a real state
            # rather than a typo -- and the list is what fixes it.
            return JSONResponse(
                {
                    "error": f"no project '{name}'",
                    "projects": [p.config.display_name for p in daemon.projects],
                },
                status_code=404,
            )
        # `_models_of` may read a file when nothing armed is bound to it.
        spec = await asyncio.to_thread(_models_of, project)
        if spec is None:
            # An answer, not a failure: a project may legitimately name none.
            return JSONResponse({"binding": None, "endpoints": []})

        declared = list(spec.providers.items())
        # Awaited, never `asyncio.run`: this handler is already on the
        # daemon's loop, and starting a second one there raises.
        catalogues = await asyncio.gather(
            *(
                # No cap: this panel *is* the catalogue, and forty of three
                # hundred shown without a word reads as all of them.
                engines.catalogue_for(provider.type, provider.base_url, limit=None)
                for _, provider in declared
            )
        )
        # Which model each role is on, so a reader can see what they are using
        # among what they could. A model may serve several roles.
        in_use: dict[str, list[str]] = {}
        for role, ref in spec.spoken_for().items():
            in_use.setdefault(ref, []).append(role)

        return JSONResponse(
            {
                "binding": {"name": spec.name, "path": str(spec.source_path)},
                "endpoints": [
                    {
                        "name": key,
                        "type": provider.type,
                        # What a person would recognise this as. The type is
                        # four products in a trench coat -- vLLM, SGLang, LM
                        # Studio, llama.cpp and every hosted router all speak
                        # `openai_compatible` -- so the type alone told a
                        # reader nothing about who they were talking to. Null
                        # when the address is one nobody wrote down, and the
                        # panel falls back to the type.
                        "label": engines.label_for(provider.type, provider.base_url),
                        # "did not answer" and "there is nothing to ask" are
                        # different facts, and a listing that conflated them
                        # would read as a fault.
                        "askable": engines.askable(provider.type),
                        # Whether this listing is what is on this machine or
                        # what the endpoint offers. Two listings that look
                        # identical and mean different things.
                        "installed": engines.lists_installed(provider.type),
                        "api_key_env": provider.api_key_env,
                        "api_key_set": _key_state(key, provider),
                        "models": [
                            {
                                "id": model.id,
                                # The one spelling of a model, built where it
                                # is always built.
                                "ref": f"{key}/{model.id}",
                                "context": model.context,
                                "size": model.size,
                                "quantization": model.quantization,
                                "capabilities": list(model.capabilities),
                                "price": (
                                    None
                                    if model.price is None
                                    else {
                                        "input": model.price[0],
                                        "output": model.price[1],
                                    }
                                ),
                                "used_by": in_use.get(f"{key}/{model.id}", []),
                            }
                            for model in served
                        ],
                    }
                    for (key, provider), served in zip(declared, catalogues)
                ],
            }
        )

    def runs(request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", "20"))
        task = request.query_params.get("task")
        # Both, for the same reason a control route takes both: `?task=chores`
        # alone would answer with every project's chores mixed together.
        project = request.query_params.get("project")
        return JSONResponse(
            {"runs": daemon.store.list_runs(limit=limit, task=task, project=project)}
        )

    def run_detail(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        events = list(daemon.store.events(run_id))
        if not events:
            return JSONResponse({"error": f"no run '{run_id}'"}, status_code=404)
        return JSONResponse({"run_id": run_id, "events": events})

    async def run_diff(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        # An index scan, like the git work below: off the loop it shares.
        summary = await asyncio.to_thread(daemon.store.summary, run_id)
        if summary is None:
            return JSONResponse({"error": f"no run '{run_id}'"}, status_code=404)

        change = summary.get("change")
        point = _workspace_for(daemon, summary.get("project"), summary.get("task"))
        if not change or point is None:
            # A run that altered nothing has nothing to review. That is an
            # answer, not a failure.
            return JSONResponse({"run_id": run_id, "change": None})

        report = await asyncio.to_thread(point.diff, change["base"], change["head"])
        return JSONResponse({"run_id": run_id, **report})

    async def _decide(request: Request, action: str, key: str) -> JSONResponse:
        """accept and discard differ only in which verb and which run id."""
        project = request.path_params["project"]
        task = request.path_params["task"]
        runner = _runner_for(daemon, project, task)
        if runner is None:
            return JSONResponse(
                {"error": f"no task '{task}' in '{project}'"}, status_code=404
            )

        point = getattr(runner, "workspace", None)
        if point is None:
            return JSONResponse(
                {"error": f"task '{task}' keeps no reviewable copy"}, status_code=409
            )

        try:
            body = await request.json()
        except Exception:
            body = {}  # an empty body means "all of it"

        run_id = (body or {}).get(key)
        target = None
        if run_id:
            summary = await asyncio.to_thread(daemon.store.summary, run_id)
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
        project = request.path_params["project"]
        task = request.path_params["task"]
        runner = _runner_for(daemon, project, task)
        if runner is None:
            return None, JSONResponse(
                {"error": f"no task '{task}' in '{project}'"}, status_code=404
            )
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

    async def flow_answer(request: Request) -> JSONResponse:
        """The person's half of a `confirm` node, over HTTP.

        Neither a review route nor a control one. It touches no file of the
        user's, so it is not review; and it outlives the process and can set a
        chain of tasks going, so it is not control either.
        """
        runner, missing = _asked(request)
        if missing is not None:
            return missing
        pending = getattr(runner, "asking", lambda: None)()
        if pending is None:
            # 409 and not 404: the task is there, it has no question open. A
            # board holding a button that has gone stale has to tell those two
            # apart, and so does anybody reading the reply in a terminal.
            return JSONResponse(
                {"error": f"task '{runner.name}' is not waiting on an answer"},
                status_code=409,
            )
        try:
            body = await request.json()
        except Exception:
            body = {}
        choice = str((body or {}).get("choice", ""))
        if not runner.answer(choice):
            # The offered ones come back with the refusal: whoever asked is
            # holding a list that is out of date, and this is the new one.
            return JSONResponse(
                {
                    "error": f"'{choice}' was not offered",
                    "choices": list((pending.asked or {}).get("choices", [])),
                },
                status_code=400,
            )
        return JSONResponse({"status": "answered", "answer": choice})

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
        task = request.query_params.get("task")
        return StreamingResponse(
            _event_stream(daemon.store, task),
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
            "poieo web UI is not built yet. The API is live: /api/tasks"
        )

    routes = [
        Route("/api/tasks", tasks),
        Route("/api/runs", runs),
        Route("/api/runs/{run_id}", run_detail),
        Route("/api/runs/{run_id}/diff", run_diff),
        Route("/api/projects/{project}/models", project_models),
        Route("/api/events", events),
        # The review: the only routes that may touch the user's own files.
        # If you are adding a third of these, stop.
        Route("/api/tasks/{project}/{task}/accept", flow_accept, methods=["POST"]),
        Route("/api/tasks/{project}/{task}/discard", flow_discard, methods=["POST"]),
        # Control: the daemon's runtime state and nothing else.
        Route("/api/tasks/{project}/{task}/pause", flow_pause, methods=["POST"]),
        Route("/api/tasks/{project}/{task}/resume", flow_resume, methods=["POST"]),
        Route("/api/tasks/{project}/{task}/run", flow_run, methods=["POST"]),
        Route("/api/tasks/{project}/{task}/answer", flow_answer, methods=["POST"]),
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
