"""The observation and control API served from inside the daemon.

Almost everything answers "what is happening / what happened". The routes that
change anything are marked again where they are registered:

- **The review** -- accept and discard, the only routes that may ever touch the
  user's own files. If you are adding a third of these, stop.
- **Control** -- pause, resume, run-now. The daemon's runtime state and nothing
  else: no file, no schedule on disk, nothing that survives a restart.
- **Editing what the reader keeps** -- pointing a role at a model, and writing
  one task card. Both change a file whose effect outlives the process, and each
  carries its own fence where it is defined.

Design: docs/web.md
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, AsyncIterator

import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

# Every suffix `card.load_cards` reads, so one name is refused in every spelling.
_CARD_SUFFIXES = {".yaml", ".yml", ".json"}
# Windows keeps these in every directory, whatever the extension is.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{n}" for n in range(1, 10)} | {f"LPT{n}" for n in range(1, 10)}

from .. import detect as engines
from ..binding import load_binding, split_ref
from ..errors import BindingError, PoieoError
from ..providers import credential_for
from ..rebind import declare, point_at
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


def _unclaimed(spec: Any) -> list[engines.Candidate]:
    """The candidates this project cannot already reach.

    **By address, not by key.** Somebody who declared the vLLM on this machine
    as `fast` has it; offering to add it again under the name detection would
    have picked writes one server into one file twice.

    `detect.one_machine` is what "the same address" means, and it is there
    rather than here because `detect` already reads addresses for `here` and
    `host`. This module had its own weaker rules beside them and was wrong for
    `http://localhost:8000` -- which `detect.ask` writes itself.

    A candidate with no address -- `claude`, which is asked through its own SDK
    -- is claimed by any endpoint of its type instead, for the same reason
    under a different spelling.
    """
    taken = {engines.one_machine(p.base_url) for p in spec.providers.values() if p.base_url}
    types = {p.type for p in spec.providers.values()}

    def reached(candidate: engines.Candidate) -> bool:
        if candidate.key in spec.providers:
            return True
        if candidate.base_url:
            return engines.one_machine(candidate.base_url) in taken
        return candidate.type in types

    return [candidate for candidate in engines.CANDIDATES if not reached(candidate)]


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
        states = await asyncio.gather(*(asyncio.to_thread(_review_state, runner) for runner in daemon.runners))
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

    def _asked_project(request: Request) -> tuple[Any, JSONResponse | None]:
        """The project a models route is about, or the 404 saying there is none.

        The refusal carries the names that *do* answer: the board remembers a
        project across restarts, so a picker holding one the daemon was started
        without is a real state rather than a typo, and the list is what fixes
        it.
        """
        name = request.path_params["project"]
        project = _project_for(daemon, name)
        if project is None:
            return None, JSONResponse(
                {
                    "error": f"no project '{name}'",
                    "projects": [p.config.display_name for p in daemon.projects],
                },
                status_code=404,
            )
        return project, None

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
        project, missing = _asked_project(request)
        if missing is not None:
            return missing
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
                engines.catalogue_for(provider.type, provider.base_url, limit=None, api_key_env=provider.api_key_env)
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
                # What a model may be pointed at: `default`, and the roles this
                # file already names. Not every role the graphs call -- offering
                # one the file has never named is how a panel creates the
                # `role: classifer` typo that binding.md spends a page on.
                "roles": ["default", *sorted(spec.roles)],
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
                        "label": engines.label_for(provider.type, provider.base_url, answered.server),
                        # "did not answer" and "there is nothing to ask" are
                        # different facts, and a listing that conflated them
                        # would read as a fault.
                        "askable": engines.askable(provider.type),
                        # Whether this listing is what is **pulled** or what the
                        # endpoint offers. Two listings that look identical and
                        # mean different things -- and a property of the
                        # backend, true of an Ollama wherever it runs.
                        "installed": engines.lists_installed(provider.type),
                        # Whose machine that is, which the type cannot answer:
                        # an inference server is routinely somewhere else, and
                        # every Ollama anywhere used to read as "on this
                        # machine". Null when there is no address to ask.
                        "here": engines.is_here(provider.base_url),
                        # Which machine, and no more of the address than that.
                        # `poieo config` names an Ollama `ollama` wherever it
                        # runs, so two of them were two endpoints a reader could
                        # not tell apart. See docs/web.md for what changed.
                        "host": engines.where(provider.base_url),
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
                            for model in answered.models
                        ],
                    }
                    for (key, provider), answered in zip(declared, catalogues)
                ],
            }
        )

    async def project_models_undeclared(request: Request) -> JSONResponse:
        """Engines answering on this machine that this project cannot reach.

        Detection otherwise runs once, at `init`: install Ollama the week after
        and the binding has never heard of it, so the panel shows nothing from
        it *and no reason why* -- which reads as "there is nothing there".

        **Its own route, and that is the design decision here.** Folded into
        the report it would have been free only if a closed port refused fast,
        and measured, it does not: a candidate nothing is listening on costs
        the full `HTTP_TIMEOUT`, so every paint of the catalogue would have
        waited a second and a half for its own footnote. Asked separately, the
        catalogue arrives when it arrives and this lands under it later --
        which is the order a reader wants them in anyway.

        A read. Nothing is written until somebody presses what it offers, and
        `models/add` is the route that does.
        """
        project, missing = _asked_project(request)
        if missing is not None:
            return missing
        spec = await asyncio.to_thread(_models_of, project)
        if spec is None:
            # Nowhere to write an answer to, so nothing here is worth a trip.
            return JSONResponse({"undeclared": []})

        found = await engines.probe(_unclaimed(spec))
        return JSONResponse(
            {
                "undeclared": [
                    {
                        "name": engine.key,
                        # What answered, preferred over the candidate's own
                        # label -- which is the pair `vLLM / SGLang` for a port
                        # two products share, and telling those apart was the
                        # whole reason to ask rather than to read a config.
                        "label": engine.known_as,
                        "type": engine.type,
                        # Ids only. This is a notice, not a second catalogue --
                        # what it has to say is *that* there is something here.
                        "models": list(engine.models),
                    }
                    for engine in found
                ]
            }
        )

    def _slug(title: str) -> str:
        """A filename from a title, or "" if nothing usable is left.

        A card's identity is its filename and the `name:` inside is a title the
        reader may rewrite, so the two are made here and never again. Anything
        that is not a letter, a digit, a dash or an underscore is dropped --
        which is also the fence: a name is the one place a path could get into
        a route whose whole promise is one file, in one folder.
        """
        # \w and not [a-z0-9_]: a title in Korean, Cyrillic or Japanese
        # slugged to nothing under ASCII, so those readers could never make a
        # card at all. The dump already writes unicode through.
        return re.sub(r"[^\w-]+", "-", title.strip().lower(), flags=re.UNICODE).strip("-")

    async def project_tasks_create(request: Request) -> JSONResponse:
        """Write one card into the project's tasks folder.

        The **fifth kind** of write here, and the first that makes a file that
        did not exist. Its effect outlives the process, which is not control;
        nothing a run wrote is involved, which is not review.

        Its own fence: **one card, in this project's tasks folder, and nothing
        else.** No graph, no binding, and no path that leaves that folder --
        the name is turned into a filename here rather than taken as one.

        Three fields and no more, which is DESIGN.md's second principle: a
        name, the folder it works in, and its prompt. The folder is required on
        purpose. It is the one thing the model's hands will touch, and filling
        it in by default would fill in the single moment the user is meant to
        see.

        Every refusal is decided before the file is opened, so a request that
        will be refused never leaves a half-written card in a folder the daemon
        is watching.
        """
        project, missing = _asked_project(request)
        if missing is not None:
            return missing
        config = project.config
        if not config.cards:
            return JSONResponse({"error": "this project names no tasks folder"}, status_code=409)
        if not config.binding:
            # A card written here names no binding of its own, so with no
            # default it would not load -- and one unloadable card in a watched
            # folder stops every later card from being noticed at all.
            return JSONResponse(
                {"error": "this project has no default models file for a new task to use"},
                status_code=409,
            )

        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body or {}
        title = str(body.get("name") or "").strip()
        prompt = str(body.get("prompt") or "").strip()
        folder = str(body.get("folder") or "").strip()

        # Refused rather than quietly rewritten. "tidy up" becoming "tidy-up"
        # is a spelling; "../escape" becoming "escape" is a different request
        # answered without saying so, and the fence is exactly here.
        if "/" in title or chr(92) in title or title.strip(".") == "":
            return JSONResponse({"error": "a task's name is not a path"}, status_code=400)
        slug = _slug(title)
        if not slug:
            return JSONResponse({"error": "a task needs a name that can be a filename"}, status_code=400)
        if not prompt:
            return JSONResponse({"error": "a task needs a prompt"}, status_code=400)
        if not folder:
            return JSONResponse(
                {"error": "a task needs the folder it works in; there is no default"},
                status_code=400,
            )

        cards = config.resolve_path(config.cards)
        # expanduser, because a card does that when it reads this back; without
        # it `~/code/x` is refused as a folder inside the tasks folder.
        asked = Path(os.path.expanduser(folder))
        # Relative to the card, because that is how a card reads it back.
        where = (asked if asked.is_absolute() else cards / asked).resolve()
        if not where.is_dir():
            return JSONResponse(
                {"error": f"the folder it would work in is not there: {where}"},
                status_code=400,
            )

        # **Inside this project, and nowhere else.** A card takes the files and
        # shell toolsets and fires within seconds of being written, so without
        # this one request starts a shell-capable agent anywhere on the machine
        # -- over a port any page in the browser can reach. Pointing a task at
        # another checkout is still done by writing the card by hand, which is a
        # deliberate act rather than a request.
        root = Path(config.base_dir).resolve()
        if root != where and root not in where.parents:
            return JSONResponse(
                {"error": f"a task made here works inside this project; {where} is outside {root}"},
                status_code=400,
            )
        # Windows answers exists() for these in every directory, and a write
        # would reach the console rather than a file.
        if slug.split(".")[0].upper() in _RESERVED:
            return JSONResponse({"error": f"'{slug}' is not a usable filename"}, status_code=400)
        path = cards / f"{slug}.yaml"
        # Every suffix load_cards reads, not only the one written: a .yml card
        # of the same name would load beside this one, and the folder would then
        # stop loading at all -- taking every later card with it.
        taken = [
            other.name for other in cards.iterdir() if other.stem == slug and other.suffix.lower() in _CARD_SUFFIXES
        ]
        if taken:
            return JSONResponse(
                {"error": f"this project already has a task called '{slug}' ({taken[0]})"},
                status_code=409,
            )

        payload = yaml.safe_dump(
            {"name": title, "folder": folder, "prompt": prompt},
            allow_unicode=True,
            sort_keys=False,
        )

        def _write() -> bool:
            # Exclusive create, so the check above and the write are one act:
            # two requests naming the same card in the same second would both
            # answer ok, and the second would overwrite the first in silence.
            try:
                with open(path, "x", encoding="utf-8") as handle:
                    handle.write(payload)
            except FileExistsError:
                return False
            return True

        if not await asyncio.to_thread(_write):
            return JSONResponse(
                {"error": f"this project already has a task called '{slug}'"},
                status_code=409,
            )
        # No reload here: the daemon watches this folder and will find it, the
        # same way it finds one written by a hand. One door, not two.
        return JSONResponse({"ok": True, "task": slug, "path": str(path)})

    async def project_models_use(request: Request) -> JSONResponse:
        """Point a role at another model, and repaint what that changed.

        The **fourth kind** of write here. It edits a file the reader keeps,
        which is not the review -- review moves what a run wrote into their own
        branch, and everything it touches was written by a run. Its effect
        outlives the process, which is not control. It is the same edit
        `poieo config use` makes, through the same `rebind.point_at`, so there
        is no second set of refusals to keep in step.

        Its own fence: **it may write the project's binding file and nothing
        else, and it never accepts or returns a credential.**

        Every refusal below is decided *before* `rebind` opens the file, so a
        request that will be refused never touches it -- and `rebind` itself
        refuses before writing on any shape it does not recognise.
        """
        project, missing = _asked_project(request)
        if missing is not None:
            return missing
        spec = await asyncio.to_thread(_models_of, project)
        if spec is None:
            return JSONResponse({"error": "this project names no models file"}, status_code=409)

        try:
            body = await request.json()
        except Exception:
            body = {}
        role = str((body or {}).get("role") or "default")
        try:
            provider, model = split_ref(str((body or {}).get("target", "")))
        except BindingError as exc:
            # 400 and not 409: the argument is malformed, not the state.
            return JSONResponse({"error": str(exc)}, status_code=400)

        declared = spec.providers.get(provider)
        if declared is None:
            return JSONResponse(
                {
                    "error": f"this project declares no endpoint '{provider}'",
                    "providers": sorted(spec.providers),
                },
                status_code=409,
            )
        # Best effort, and only when the endpoint answers: a laptop with its
        # server switched off still gets to edit its own config, exactly as
        # `poieo config use` allows. But a model named from memory is the typo
        # this exists to prevent, so an answer is believed.
        answered = await engines.catalogue_for(
            declared.type, declared.base_url, limit=None, api_key_env=declared.api_key_env
        )
        served = [one.id for one in answered.models]
        if served and model not in served:
            return JSONResponse(
                {
                    "error": f"'{provider}' does not serve '{model}'",
                    "models": served,
                },
                status_code=409,
            )

        path = project.config.default_binding_path()
        try:
            await asyncio.to_thread(point_at, path, role, provider, model)
        except PoieoError as exc:
            # `rebind` refuses before writing when it cannot find what it came
            # to change, and names the file and the key. Said in its words.
            return JSONResponse({"error": str(exc)}, status_code=409)

        # The board draws a model on every node off the spec in memory, so
        # without this the file and the picture part company until the next
        # run re-reads it.
        refused = ""
        try:
            await asyncio.to_thread(daemon.reread, str(path))
        except PoieoError as exc:
            # The edit landed -- `point_at` verified the file reloads -- but the
            # daemon validates what start-up validates, and may keep the last
            # good spec instead. Pointing a role at an endpoint whose key is not
            # set is the case that happens, and it used to pass silently.
            #
            # It cannot. The panel reads the same in-memory spec, so it redraws
            # the *old* model, and a reader who was told "using" watches nothing
            # change. Worse, the file is now a state the project will not start
            # from. Saying which of the two happened is the whole answer.
            refused = str(exc)

        return JSONResponse(
            {
                "status": "using",
                "role": role,
                "ref": f"{provider}/{model}",
                # Said out loud rather than implied: silence from an endpoint
                # is not the same as its agreement.
                "checked": bool(served),
                # Whether the running daemon took it, and not just the file.
                "adopted": not refused,
                **({"why": refused} if refused else {}),
            }
        )

    async def project_models_add(request: Request) -> JSONResponse:
        """Let this project use an engine already answering on this machine.

        The other write on this route, under the same fence, and the browser
        form of `poieo config add` -- through the same `rebind.declare`, so
        there is not a second set of rules about what may be written.

        **Only adds.** Nothing about what a role uses moves; declaring a model
        and choosing one are different decisions, and the second is
        `models/use`. An endpoint already declared is left exactly as it is,
        since somebody may have pointed it at another port.

        The engine is named back by **key**, not by address: the board was
        never told where any of these live, and the table detection looks in
        is the one place that knows.
        """
        project, missing = _asked_project(request)
        if missing is not None:
            return missing
        spec = await asyncio.to_thread(_models_of, project)
        if spec is None:
            return JSONResponse({"error": "this project names no models file"}, status_code=409)

        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body or {}
        url = str(body.get("url", "")).strip()
        wanted = str(body.get("engine", ""))

        # A **name**, never a key. The variable is not a secret and belongs in
        # the file; the value belongs in the environment, and this route would
        # not know what to do with one if it were sent.
        key_env = str(body.get("key_env") or "")
        if key_env and not url:
            # The four ports detection looks at on this machine are not
            # endpoints a key opens, and there would be no saying which of them
            # it was meant for. Dropped in silence it left a caller believing
            # they had declared a keyed endpoint they had not.
            return JSONResponse(
                {"error": "a key variable names the key for one address; send the address too"},
                status_code=400,
            )

        if url:
            # An address nobody detected. `CANDIDATES` knows four ports on this
            # machine, and an inference server is routinely somewhere else --
            # so the reader types where it is and this asks what is there,
            # rather than a form asking them to classify their own server.
            #
            # Asked *with* the key: an endpoint that wants one answers 401 to a
            # listing, so the endpoints this field exists for were the ones it
            # could not add.
            found = await engines.ask(url, key_env or None)
            if found is None:
                if key_env and not os.environ.get(key_env):
                    # Only on the way out, never as a precondition: the key may
                    # live in the environment a wrapper starts the daemon under
                    # rather than this one, and an endpoint that lists without a
                    # key still declares. But a 401 reads to detection as
                    # silence, and "nothing usable answered" alone is a true
                    # sentence about the wrong problem.
                    return JSONResponse(
                        {
                            "error": f"nothing usable answered at {url}, and ${key_env} is not set where the "
                            f"daemon is running -- if that endpoint wants a key, it was asked without one"
                        },
                        status_code=409,
                    )
                return JSONResponse(
                    {"error": f"nothing usable answered at {url} -- no listing, or one with no models on it"},
                    status_code=409,
                )
            found = replace(found, key=str(body.get("name") or found.key))
            if found.key in spec.providers:
                return JSONResponse(
                    {
                        "error": f"this project already declares '{found.key}' -- "
                        f"give this one another name, since one already there is never overwritten"
                    },
                    status_code=409,
                )
            answered = [found]
        elif wanted:
            candidate = next((one for one in _unclaimed(spec) if one.key == wanted), None)
            if candidate is None:
                if any(one.key == wanted for one in engines.CANDIDATES):
                    # It exists; this project already has it. The offer was
                    # drawn from a report taken a moment ago, and a terminal may
                    # have added it in between.
                    return JSONResponse(
                        {"error": f"this project already reaches '{wanted}'"},
                        status_code=409,
                    )
                # 400, not 409: the argument names nothing detection knows how
                # to look for, which is malformed rather than a changeable state.
                return JSONResponse(
                    {
                        "error": f"'{wanted}' is not an engine this looks for",
                        "engines": [one.key for one in engines.CANDIDATES],
                    },
                    status_code=400,
                )
            # Asked again, because the press is a second trip: it answered when
            # the panel was painted and may not now, and writing an address that
            # serves nothing is a binding that fails on the project's next run.
            # The rule `probe` holds, held here for the same reason.
            answered = await engines.probe([candidate])
            if not answered:
                return JSONResponse(
                    {"error": f"'{candidate.key}' is not answering on this machine"},
                    status_code=409,
                )
        else:
            return JSONResponse(
                {"error": "name an engine this machine is running, or the address of one"},
                status_code=400,
            )

        path = project.config.default_binding_path()
        try:
            added = await asyncio.to_thread(declare, path, answered)
        except PoieoError as exc:
            # `rebind` writes, sees the result will not load, and puts the file
            # back exactly as it was. Its words, naming the file.
            return JSONResponse({"error": str(exc)}, status_code=409)
        if not added:
            # `_models_of` answers from the spec in memory, which a terminal
            # edit can leave a step behind the file. `declare` read the file,
            # so it is the one that found out.
            return JSONResponse(
                {"error": f"this project already reaches '{answered[0].key}'"},
                status_code=409,
            )

        # Without this the panel would go on offering what it just wrote, and
        # the board would keep drawing the endpoints of a file that has moved.
        try:
            await asyncio.to_thread(daemon.reread, str(path))
        except PoieoError:
            # The write landed and `declare` verified it reloads; a daemon that
            # will not adopt it is the next run's problem to report.
            pass

        return JSONResponse(
            {
                "status": "added",
                "engine": answered[0].key,
                "models": list(answered[0].models),
            }
        )

    def runs(request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", "20"))
        task = request.query_params.get("task")
        # Both, for the same reason a control route takes both: `?task=chores`
        # alone would answer with every project's chores mixed together.
        project = request.query_params.get("project")
        return JSONResponse({"runs": daemon.store.list_runs(limit=limit, task=task, project=project)})

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
            return JSONResponse({"error": f"no task '{task}' in '{project}'"}, status_code=404)

        point = getattr(runner, "workspace", None)
        if point is None:
            return JSONResponse({"error": f"task '{task}' keeps no reviewable copy"}, status_code=409)

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
                return JSONResponse({"error": f"run '{run_id}' has no change"}, status_code=404)
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
            return None, JSONResponse({"error": f"no task '{task}' in '{project}'"}, status_code=404)
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
        return PlainTextResponse("poieo web UI is not built yet. The API is live: /api/tasks")

    routes = [
        Route("/api/tasks", tasks),
        Route("/api/runs", runs),
        Route("/api/runs/{run_id}", run_detail),
        Route("/api/runs/{run_id}/diff", run_diff),
        Route("/api/projects/{project}/models", project_models),
        # Its own read rather than a field on the one above: a candidate port
        # nothing is listening on costs a full timeout, and the catalogue must
        # not wait on its own footnote.
        Route("/api/projects/{project}/models/undeclared", project_models_undeclared),
        # Models: the fourth kind. They write the project's binding file and
        # nothing else, and never accept or return a credential. `add` declares
        # an endpoint; `use` chooses among the models of one already declared.
        # Two decisions, kept apart here as `poieo config` keeps them apart.
        Route(
            "/api/projects/{project}/models/use",
            project_models_use,
            methods=["POST"],
        ),
        Route(
            "/api/projects/{project}/models/add",
            project_models_add,
            methods=["POST"],
        ),
        # Making: the fifth kind. It creates a file that did not exist, in the
        # folder the daemon watches, and nothing else -- one card, inside this
        # project.
        Route(
            "/api/projects/{project}/tasks",
            project_tasks_create,
            methods=["POST"],
        ),
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
        routes.append(Mount("/assets", ImmutableFiles(directory=assets), name="assets"))
    return Starlette(routes=routes)
