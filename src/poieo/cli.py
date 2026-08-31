"""Command line front end.

Every command is a thin wrapper over the library, so the web editor that comes
later can call the same functions without shelling out.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, NoReturn, Optional

import typer
import yaml

if TYPE_CHECKING:  # `_board` names httpx in an annotation; the import is deferred
    import httpx  # because starting the CLI must not pay for the HTTP stack.

# Model output is arbitrary Unicode; legacy Windows console codepages (cp949,
# cp1252, ...) cannot encode all of it and would crash every `poieo run` that
# prints a fancy dash. Reconfigure rather than crash.
for _stream in (sys.stdout, sys.stderr):
    if _stream and _stream.encoding and _stream.encoding.lower() not in ("utf-8", "utf8"):
        _stream.reconfigure(errors="replace")

from dataclasses import replace

from . import __version__
from . import detect as engines
from .binding import load_binding, split_ref
from .card import (
    CardSpec,
    append_journal,
    build_graph,
    card_payload,
    expand,
    is_card_file,
    load_card,
    load_cards,
    read_journal,
    record_run,
)
from .daemon import Daemon, load_config
from .daemon.config import (
    DaemonConfig,
    TaskSpec,
    check_isolation,
    config_for_tasks_folder,
)
from .editor import render_editor
from .errors import BindingError, PoieoError
from .graph import GraphSpec, load_graph
from .layout import layout_for
from .learn import last_suggestion
from .learn import learn as run_learning_pass
from .memory import keeps_memory, memory_report, read_memory
from .project import (
    MARKER,
    MOCK_BINDING,
    binding_document,
    find_project,
    find_project_file,
    init_project,
    load_project,
    nothing_found,
)
from .providers import ProviderPool
from .rebind import already, declare, point_at
from .runtime.executor import execute, needs_a_workdir, preflight
from .store import NullStore, RunStore
from .tools import Isolation, ToolContext
from .viewer import mermaid_source, render_page
from .workspace import Workspace

# The front page is grouped by what a person is trying to do, in the order
# they will do it. A panel title is one of the user's three words -- a task, a
# run, a change -- and never a layer of the design: DESIGN.md principle 7 is
# that worktrees, bindings and providers are machinery, and machinery
# does not appear in the interface. Least of all on the first screen.
SETUP = "Setting up"
BOARD = "Your tasks"
AFTER = "What happened"

app = typer.Typer(
    name="poieo",
    help="Write down the work you want done. The models on your own machine "
    "keep it running, and you read what they did in the morning.",
    epilog="New here? `poieo init` sets this folder up, then `poieo run tasks/hello.yaml` tries it once.",
    no_args_is_help=True,
    add_completion=False,
)
runs_app = typer.Typer(name="runs", help="What has run, and what each run did.", no_args_is_help=True)
app.add_typer(runs_app, rich_help_panel=AFTER)

# Bare `poieo config` reports rather than printing help: "what am I bound to"
# is the question people arrive with, and making them find a subcommand to ask
# it is a tax. The subcommands are for changing the answer.
config_app = typer.Typer(
    name="config",
    help="Which models this project uses, and what else this machine has.",
    invoke_without_command=True,
)
app.add_typer(config_app, rich_help_panel=SETUP)


def _reader_left(exc: BaseException, windows: bool = os.name == "nt") -> bool:
    """Whether this is the thing reading our output having stopped reading.

    `poieo runs list | head` is an ordinary thing to type, and `head` closes
    the pipe the moment it has enough. POSIX calls that EPIPE, which Python
    raises as BrokenPipeError. Windows calls it EINVAL on a plain OSError --
    the same thing it says about a path it will not accept, and the only thing
    separating the two is that a file operation names the file it failed on
    and a write to a stream has no name to give.

    Asked as a question about a platform rather than about *this* platform, so
    a machine that is not Windows can still hold the Windows answer -- the same
    shape `posix_shell(windows=...)` uses.
    """
    if isinstance(exc, BrokenPipeError):
        return True
    return windows and isinstance(exc, OSError) and exc.errno == errno.EINVAL and exc.filename is None


def _guarded(fn):
    """Every command fails in the product's voice, never with a traceback.

    Applied at registration, so no command can forget it.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PoieoError as exc:
            _fail(str(exc))
        except OSError as exc:
            if not _reader_left(exc):
                raise
            # Nobody is listening, so there is nothing to report and nowhere to
            # report it. Point the stream at nothing on the way out: the
            # interpreter flushes it once more as it shuts down, and *that*
            # failure prints `Exception ignored in: <_io.TextIOWrapper ...>`
            # after the command has already returned -- which is the part a
            # person actually sees, on their screen, after a pipeline that
            # worked.
            with contextlib.suppress(OSError, ValueError, io.UnsupportedOperation):
                nowhere = os.open(os.devnull, os.O_WRONLY)
                os.dup2(nowhere, sys.stdout.fileno())
                os.close(nowhere)
            # Zero, because nothing went wrong. The pipeline's own status is
            # the reader's -- `| head` succeeded, and it is what the shell asks.
            raise typer.Exit(code=0)

    return wrapper


def _fail(message: str) -> NoReturn:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _ok(message: str) -> None:
    typer.secho(message, fg=typer.colors.GREEN)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_input(raw: Optional[str], pairs: list[str]) -> dict[str, Any]:
    """Build the run payload from ``--input`` (JSON or @file) and ``--set k=v``."""
    payload: dict[str, Any] = {}
    if raw:
        text = raw
        if raw.startswith("@"):
            path = Path(raw[1:])
            if not path.exists():
                _fail(f"input file not found: {path}")
            text = path.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            _fail(f"--input is not valid JSON: {exc}")
        if not isinstance(data, dict):
            _fail("--input must be a JSON object")
        payload.update(data)
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            _fail(f"--set expects key=value, got {pair!r}")
        try:  # let `--set retries=3` arrive as an int, not "3"
            payload[key] = json.loads(value)
        except json.JSONDecodeError:
            payload[key] = value
    return payload


@app.command(hidden=True)
@_guarded
def version() -> None:
    """Print the poieo version."""
    typer.echo(f"poieo {__version__}")


@app.command(rich_help_panel=SETUP)
@_guarded
def init(
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Lay the project out against the scripted mock model, without looking for a real one.",
    ),
    name: Optional[str] = typer.Option(None, "--name", help="What a board calls this project [default: the folder]."),
) -> None:
    """Set this folder up as a poieo project.

    Looks at the machine once -- every local server that answers, and a Claude
    credential if there is one -- and writes all of them into the binding, so a
    role can name any of them later without another round of detection.

    Existing files are never touched; run it twice and the second run changes
    nothing.
    """
    if mock:
        body = MOCK_BINDING
        reason = "mock -- asked for; it answers from a script, not a model"
        found = []
    else:
        found = engines.detect()
        if not found:
            # Better an empty folder than a project that runs all night on
            # invented text. --mock is the way to say you meant it.
            _fail(nothing_found())
        engine = found[0]
        body = binding_document(found, (engine.key, engine.models[0]))
        reason = f"{engine.known_as} -- {engine.models[0]}"

    report = init_project(Path.cwd(), body, name=name)
    for action, relative in report:
        line = f"{action}  {relative}"
        if relative == "models/default.yaml":
            line += f"   ({reason})"
        typer.echo(line)

    # A flag that quietly did nothing is worse than one that refuses: existing
    # files are never touched, so a --name against a project that already has a
    # poieo.yaml has to say where the name it was given went.
    if name and ("kept", "poieo.yaml") in report:
        typer.echo("")
        typer.echo(
            f'poieo.yaml was already here, so the name stayed as it is -- set `name: {name}` in it to use "{name}"'
        )

    # Automatic is fine, invisible is not: the whole pool is in the file, so
    # say what else is in it rather than leaving it to be discovered.
    others = [spare.known_as for spare in found[1:]]
    if others:
        typer.echo("")
        typer.echo(f"also declared, ready for a role to name: {', '.join(others)}")
    typer.echo("")
    typer.echo("next:")
    typer.echo("  poieo run tasks/hello.yaml    run the sample card once")
    typer.echo("  poieo daemon                  keep this project's tasks running")


_NO_BINDING = (
    "no binding: pass one with -b, add `binding: <file>` to the card, "
    "or set a default in a poieo.yaml (`poieo init` writes one)"
)


def _find_binding(
    binding: "Path | None", task: "CardSpec | None", where: "Path | None" = None
) -> "tuple[Path | None, Path | None]":
    """The binding chain: the flag, then the card, then the card's project.

    ``supplied_by`` is the poieo.yaml that filled the silence, None when the
    user named the binding. Automatic is fine, invisible is not, so callers
    echo it.

    The project is the card's, found from ``where`` the card sits -- not from
    where the terminal happens to be. Searched from the working directory, the
    same card run from two places got two different bindings, and a card under
    no project at all quietly borrowed one from whatever the shell was standing
    in. The store already resolves this way (``layout_for(task.dir)``); this is
    the same rule for the binding.

    ``where`` is passed rather than read off the card because callers expand a
    card before they get here, and an expanded card is a different object with
    no directory of its own. The path the user named always has one.
    """
    if binding is not None:
        return binding, None
    if task is not None and task.binding:
        return task.resolve(task.binding), None
    project = find_project(where)
    if project is not None and project.binding:
        return project.resolve_path(project.binding), project.source_path
    return None, None


def _project_file(named: "Path | None") -> Path:
    """The config to work from: the one the user named, or the project's.

    One place, so the refusal below has one wording.
    """
    if named is not None:
        return named
    found = find_project_file()
    if found is None:
        _fail("no poieo.yaml found here or above; pass a config file, or run `poieo init`")
    return found


def _load_card(path: Path) -> "CardSpec | None":
    """The task a path names, or None for a plain graph. Load it once per
    command and pass it down; every helper here would otherwise reopen it."""
    return load_card(path) if is_card_file(path) else None


def _load_spec(path: Path, task: "CardSpec | None" = None) -> GraphSpec:
    """Load a graph, or the graph a task file stands for."""
    task = task or _load_card(path)
    if task is None:
        return load_graph(path)
    if task.graph:
        return load_graph(task.resolve(task.graph))
    return build_graph(task)


@app.command(rich_help_panel=SETUP)
@_guarded
def validate(
    graph_path: Path = typer.Argument(..., help="Graph or task YAML/JSON file."),
    binding: Optional[Path] = typer.Option(
        None, "--binding", "-b", help="Also check every role resolves in this binding."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON."),
) -> None:
    """Prove a task loads now, rather than at 3am when it fires."""
    task = _load_card(graph_path)
    graph = _load_spec(graph_path, task)
    # One report, two renderings: the facts are gathered once so the JSON an
    # agent parses can never drift from the lines a person reads.
    report: dict[str, Any] = {
        "graph": graph.name,
        "version": graph.version,
        "nodes": len(graph.nodes),
        "entry": graph.entry,
        "roles": sorted(graph.roles()),
        "valid": True,
    }
    if task is not None:
        # The whole card, not just its graph: a schedule that cannot
        # parse must fail here, not when the daemon is armed.
        task, _ = expand(task)
        report["schedule"] = task.trigger.build().describe

    homeless = needs_a_workdir(graph)
    if homeless:
        report["workdir_open"] = homeless

    binding, supplied_by = _find_binding(binding, task, graph_path.parent)
    if binding:
        try:
            spec = load_binding(binding)
            preflight(graph, spec, require_workdir=False)
        except PoieoError as exc:
            _fail(str(exc))
        report["binding"] = {
            "name": spec.name,
            "path": str(binding),
            "from": str(supplied_by) if supplied_by is not None else None,
            "roles": {role: r.ref for role in sorted(graph.roles()) for r in (spec.resolve(role),)},
        }

    if as_json:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    if "schedule" in report:
        typer.echo(f"schedule   {report['schedule']}")
    typer.echo(f"graph      {graph.name} v{graph.version}  ({len(graph.nodes)} nodes)")
    typer.echo(f"entry      {graph.entry}")
    typer.echo(f"roles      {', '.join(report['roles']) or '(none)'}")
    if homeless:
        # Not a defect: a graph that names no directory is one that can move.
        typer.echo(f"workdir    supplied at run time for {', '.join(homeless)}")
    if "binding" in report:
        origin = f"  (from {supplied_by})" if supplied_by is not None else ""
        typer.echo(f"binding    {report['binding']['name']}{origin}")
        for role, target in report["binding"]["roles"].items():
            typer.echo(f"           {role} -> {target}")
    _ok("valid")


@app.command(hidden=True)
@_guarded
def show(
    graph_path: Path = typer.Argument(..., help="Graph or task YAML/JSON file."),
    mermaid: bool = typer.Option(False, "--mermaid", help="Emit a mermaid flowchart."),
) -> None:
    """Print what a graph -- or what a task expands to -- looks like."""
    graph = _load_spec(graph_path)

    if mermaid:
        typer.echo(mermaid_source(graph))
        return

    typer.echo(f"{graph.name} v{graph.version}")
    if graph.description:
        typer.echo(f"  {graph.description}")
    for node in graph.nodes:
        marker = "*" if node.id == graph.entry else " "
        detail = (
            f"role={node.role or graph.default_role}"
            if node.type == "agent"
            else (node.command or f"{node.language} script")
            if node.type == "command"
            else f"{len(node.branches)} branch(es)"
        )
        typer.echo(f" {marker} {node.id:<16} {node.type:<7} {detail}")
        for branch in node.branches:
            typer.echo(f"      when {branch.when}  ->  {branch.to or '(end)'}")
        if node.type == "router":
            typer.echo(f"      default        ->  {node.default or '(end)'}")
        elif node.next:
            typer.echo(f"      next           ->  {node.next}")


@app.command(hidden=True)
@_guarded
def view(
    graph_paths: list[Path] = typer.Argument(..., help="One or more graph files."),
    binding: Optional[Path] = typer.Option(None, "--binding", "-b", help="Show which model each role resolves to."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Where to write the page [./<name>.html]."),
    serve: bool = typer.Option(False, "--serve", help="Serve the page over http instead of just writing it."),
    port: int = typer.Option(8765, "--port", help="Port for --serve."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface for --serve."),
) -> None:
    """Render graphs as a browsable HTML page."""
    graphs = [_load_spec(path) for path in graph_paths]
    spec = load_binding(binding) if binding else None

    title = graphs[0].name if len(graphs) == 1 else f"{len(graphs)} workflows"
    page = render_page(graphs, spec, title=title)

    # A page you asked for, in the folder you asked from. Nothing reads it back.
    target = output or Path(f"{graphs[0].name}.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    _ok(f"wrote {target}")

    if not serve:
        typer.echo(f"open file://{target.resolve()}")
        return

    _serve_directory(target, host, port)


def _serve_directory(target: Path, host: str, port: int) -> None:
    """Serve the page's directory until interrupted."""
    import functools
    import http.server
    import socketserver

    directory = str(target.parent.resolve())
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    # The mermaid bundle loads from a CDN, so the page needs a real origin
    # rather than file:// to render in a strict browser.
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer((host, port), handler) as httpd:
            url = f"http://{host}:{port}/{target.name}"
            typer.secho(f"serving {url}  (ctrl-c to stop)", fg=typer.colors.CYAN)
            httpd.serve_forever()
    except OSError as exc:
        _fail(f"cannot bind {host}:{port}: {exc}")
    except KeyboardInterrupt:
        typer.echo("\nstopped")


def _jupyter_session() -> dict[str, Any]:
    """Find a running Jupyter server so the editor can save through its API."""
    import subprocess

    try:
        proc = subprocess.run(
            ["jupyter", "server", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    for line in proc.stdout.splitlines():
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue
        if info.get("token") is not None:
            return info
    return {}


@app.command(hidden=True)
@_guarded
def edit(
    graph_path: Path = typer.Argument(..., help="Graph file to edit."),
    binding: Optional[Path] = typer.Option(None, "--binding", "-b", help="Show which model each role resolves to."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Where to write the editor page."),
    save_via: str = typer.Option(
        "auto",
        "--save-via",
        help="How the page saves: auto | jupyter | none (download/copy only).",
    ),
    token: Optional[str] = typer.Option(None, "--token", help="Jupyter token."),
    root: Optional[Path] = typer.Option(None, "--jupyter-root", help="Jupyter's root_dir, for building the save path."),
    serve: bool = typer.Option(False, "--serve", help="Serve the page over http."),
    port: int = typer.Option(8765, "--port"),
    host: str = typer.Option("127.0.0.1", "--host"),
) -> None:
    """Open a graph in the drag-and-drop canvas editor."""
    if is_card_file(graph_path):
        # The editor saves back over what it opened, and a task is not a graph.
        _fail(f"{graph_path} is a task; run 'poieo eject' first, then edit the graph")
    graph = load_graph(graph_path)
    spec = load_binding(binding) if binding else None

    resolved_graph = graph_path.resolve()
    save: dict[str, Any] = {"mode": "none", "filename": resolved_graph.name}

    if save_via in ("auto", "jupyter"):
        session = _jupyter_session()
        jupyter_root = root or (Path(session["root_dir"]) if session.get("root_dir") else None)
        jupyter_token = token or session.get("token")
        if jupyter_token and jupyter_root:
            try:
                relative = resolved_graph.relative_to(Path(jupyter_root).resolve())
            except ValueError:
                relative = None
            if relative is not None:
                save = {
                    "mode": "jupyter",
                    # Relative so the page saves through whatever origin served
                    # it -- a proxy hostname does not need to be known here.
                    "url": f"/api/contents/{relative.as_posix()}",
                    "path": relative.as_posix(),
                    "token": jupyter_token,
                    "filename": resolved_graph.name,
                }
            elif save_via == "jupyter":
                _fail(f"{resolved_graph} is not under Jupyter's root ({jupyter_root})")
        elif save_via == "jupyter":
            _fail("no running Jupyter server found; pass --token and --jupyter-root")

    page = render_editor(graph, spec, save=save)
    target = output or Path(f"{graph.name}-edit.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    _ok(f"wrote {target}")

    if save["mode"] == "jupyter":
        typer.echo(f"saves to    {save['path']} (via the Jupyter contents API)")
    else:
        typer.secho(
            "no save backend: the page offers download and copy instead",
            fg=typer.colors.YELLOW,
        )

    if serve:
        _serve_directory(target, host, port)
    else:
        typer.echo(f"open file://{target.resolve()}")


@app.command(rich_help_panel=BOARD)
@_guarded
def run(
    graph_path: Path = typer.Argument(..., help="Graph or task YAML/JSON file."),
    binding: Optional[Path] = typer.Option(
        None,
        "--binding",
        "-b",
        help="Binding YAML/JSON file [default: what the card names].",
    ),
    input_json: Optional[str] = typer.Option(None, "--input", "-i", help="Run payload as JSON, or @file.json."),
    set_: list[str] = typer.Option([], "--set", "-s", help="Payload override, key=value. Repeatable."),
    workdir: Optional[Path] = typer.Option(
        None, "--workdir", "-w", help="Where agent nodes work, if the graph leaves it open."
    ),
    store: Optional[Path] = typer.Option(
        None,
        "--store",
        help="Where a run's events and result go [default: the project's runs/].",
    ),
    no_log: bool = typer.Option(False, "--no-log", help="Do not write a run log."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    isolate: Optional[str] = typer.Option(None, "--isolate", help="Run commands isolated, using this image."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run one task now, and say what it did."""
    _setup_logging(verbose)
    task = _load_card(graph_path)
    graph = _load_spec(graph_path, task)
    # The flag wins; otherwise the card answers for itself; otherwise the
    # project does.
    binding, supplied_by = _find_binding(binding, task, graph_path.parent)
    if binding is None:
        _fail(_NO_BINDING)
    spec = load_binding(binding)
    if supplied_by is not None and not as_json:
        typer.echo(f"binding    {binding}  (from {supplied_by})")

    # The card says where it works; the flag still wins. A card's graph does
    # not name a folder -- the daemon supplies its private copy of one -- so
    # by hand it is the card that has to.
    if workdir is None and task is not None and task.folder:
        workdir = task.folder_path()

    card_input = card_payload(task) if task is not None else {}
    payload = {**card_input, **_parse_input(input_json, set_)}
    if store is None:
        # Asked from the card's own folder, not the cwd: a card run by hand and
        # the same card run by the daemon write one history, not two.
        store = layout_for(task.dir if task is not None else Path.cwd()).runs()
    run_store = NullStore() if no_log else RunStore(store)

    # A build cache for compiled scripts, in the project if there is one --
    # `LocalExecutor` falls back to the OS temp dir when there is not.
    here = find_project()
    tool_context = ToolContext(
        isolation=Isolation(image=isolate) if isolate else None,
        build_cache=(here.layout().cache() / "builds") if here else None,
    )
    isolation = tool_context.isolation if tool_context else None
    if isolation is not None:
        # The daemon's preflight, for the same reason: better here than eight
        # turns in. No container is kept -- a one-shot run has no next run.
        check_isolation([TaskSpec(name="adhoc", graph=str(graph_path), isolation=isolation)])

    async def _go():
        async with ProviderPool(spec) as pool:
            return await execute(
                graph,
                spec,
                pool,
                run_store,
                input=payload,
                workdir=workdir,
                tool_context=tool_context,
            )

    result = asyncio.run(_go())
    if task is not None:
        # The journal contract: every run of a task leaves a line, or the
        # next run redoes this one's work and notes are never consumed.
        record_run(task, result)

    if as_json:
        typer.echo(json.dumps(result.__dict__, indent=2, ensure_ascii=False, default=str))
    else:
        color = typer.colors.GREEN if result.status == "completed" else typer.colors.RED
        typer.secho(f"{result.status}  {result.run_id}", fg=color)
        typer.echo(f"path       {' -> '.join(result.path)}")
        typer.echo(f"tokens     in={result.usage['input_tokens']} out={result.usage['output_tokens']}")
        if result.error:
            typer.secho(f"error      {result.error}", fg=typer.colors.RED)
            if result.cause:
                typer.echo(f"cause      {result.cause['said']}")
                typer.echo(f"try        {result.cause['fix']}")
        for node_id, value in result.outputs.items():
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            typer.echo(f"\n--- {node_id} ---\n{rendered}")

    if result.status != "completed":
        raise typer.Exit(code=1)


@app.command(hidden=True)
@_guarded
def reset(
    task_path: Path = typer.Argument(..., help="Task YAML/JSON file."),
) -> None:
    """Throw away a task's isolated environment. It is rebuilt on the next run."""
    task = load_card(task_path)

    if not task.isolation:
        _ok(f"'{task.name}' does not run isolated; there is nothing to reset")
        return

    from .tools import docker

    available, reason = docker.docker_available()
    if not available:
        _fail(reason)
    folder = task.folder_path()
    if folder is None:
        return _ok(f"task '{task.slug}' works on no folder; nothing to clean.")
    removed = docker.remove_containers_for(folder)
    # The one thing the user needs to hear: their files are fine. Everything
    # this throws away is rebuilt the next time the task runs.
    _ok(f"reset '{task.name}': {removed} environment(s) thrown away. Nothing in {folder} was touched.")


def _daemon_config(config_path: "Path | None") -> "DaemonConfig":
    """One argument to `poieo daemon`, read as a project."""
    config_path = _project_file(config_path)
    if config_path.is_dir():
        # A folder with a marker in it is that project -- `poieo daemon ../notes`
        # is how a second project gets named, and pointing at a project root
        # meaning "read every file in here as a card" helps nobody.
        marker = config_path / MARKER
        if marker.exists():
            return load_config(marker)
        # Otherwise `poieo daemon tasks/`, the natural guess once cards exist:
        # a spelling of the same thing, not an error.
        return config_for_tasks_folder(config_path)
    if is_card_file(config_path):
        _fail(
            f"'{config_path}' is a single task. "
            f"`poieo run {config_path}` runs it once; to keep it "
            f"running, point the daemon at its folder: "
            f"`poieo daemon {config_path.parent}`"
        )
    return load_config(config_path)


@app.command(rich_help_panel=BOARD)
@_guarded
def daemon(
    config_paths: Optional[List[Path]] = typer.Argument(
        None,
        help="One or more project files or task folders [default: the project's poieo.yaml].",
    ),
    once: bool = typer.Option(False, "--once", help="Firing each task a single time, then exit."),
    task: Optional[str] = typer.Option(None, "--task", help="Run only this task from the config."),
    port: int = typer.Option(8484, "--port", help="Web observation UI port."),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Where the board listens. Anything but localhost has no password on it.",
    ),
    no_web: bool = typer.Option(False, "--no-web", help="Disable the web UI."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Keep the tasks running, and serve the board in a browser."""
    _setup_logging(verbose)
    # One board, as many projects as were named. No argument still means the
    # project you are standing in, which is what it has always meant.
    given = list(config_paths or [None])
    configs = [_daemon_config(each) for each in given]

    if task:
        # Narrowed across everything given: the flag names a task, and which
        # project it lives in is not something the user should have to say.
        found = False
        for config in configs:
            matching = [f for f in config.tasks if f.name == task]
            config.tasks = matching
            found = found or bool(matching)
        if not found:
            where = ", ".join(str(c.source_path) for c in configs)
            _fail(f"no task named '{task}' in {where}")
        configs = [c for c in configs if c.tasks]

    if once:
        # A single pass per task: cap iterations and make interval tasks fire
        # immediately instead of waiting out their first period.
        for config in configs:
            for spec in config.tasks:
                spec.trigger.max_iterations = 1
                spec.trigger.run_at_start = True
                if spec.trigger.type == "manual":
                    spec.trigger = spec.trigger.model_copy(update={"type": "loop"})

    try:
        results = asyncio.run(Daemon(configs, web_port=None if no_web else port, web_host=host).serve())
    except KeyboardInterrupt:  # pragma: no cover - interactive
        raise typer.Exit(code=130)

    failed = [r for r in results if r.status != "completed"]
    if once:
        typer.echo(f"\n{len(results)} run(s), {len(failed)} not completed")
    if failed:
        raise typer.Exit(code=1)


async def _roomier_than_it_is(spec: Any, pool: Any) -> list[str]:
    """Roles whose binding claims more room than the endpoint reports.

    A window declared larger than the endpoint gives means the conversation is
    cleared later than the endpoint allows -- which is the failure the runtime
    now catches, and which is much cheaper to hear about here.

    Said, never enforced. The binding wins on purpose: somebody who wrote a
    number down meant it, and the endpoint's answer can be **absent** (Ollama
    reports nothing for a model it has not loaded) or **stale** (`num_ctx` is
    whatever the last request asked for). Refusing to start over either would
    be worse than the thing it prevents, and the runtime catches the
    consequence either way.
    """
    said: list[str] = []
    seen: set[tuple[str, str]] = set()
    for role in sorted({*spec.roles, "default"}):
        try:
            resolved = spec.resolve(role)
        except PoieoError:
            continue
        if not resolved.context:
            continue
        key = (resolved.provider_name, resolved.model)
        if key in seen:
            continue
        seen.add(key)
        try:
            actual = await pool.get(resolved.provider_name).context_for(resolved.model)
        except PoieoError:
            continue
        # No answer is not a disagreement.
        if actual and resolved.context > actual:
            said.append(
                f"warn {role:<16} declares context: {resolved.context} but "
                f"{resolved.provider_name} reports {actual} for {resolved.model} "
                f"-- the conversation will be cleared later than this endpoint allows"
            )
    return said


@app.command("check", rich_help_panel=SETUP)
@_guarded
def check_providers(
    binding: Optional[Path] = typer.Option(
        None,
        "--binding",
        "-b",
        help="Binding YAML/JSON file [default: the project's].",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the probe results as JSON."),
) -> None:
    """Ask each model endpoint whether it is answering."""
    binding, _ = _find_binding(binding, None)
    if binding is None:
        _fail(_NO_BINDING)
    spec = load_binding(binding)

    async def _go() -> tuple[list[tuple[str, bool, str]], list[str]]:
        rows: list[tuple[str, bool, str]] = []
        async with ProviderPool(spec) as pool:
            for name in spec.providers:
                try:
                    healthy, detail = await pool.get(name).health()
                except PoieoError as exc:
                    healthy, detail = False, str(exc)
                rows.append((name, healthy, detail))
            return rows, await _roomier_than_it_is(spec, pool)

    rows, warnings = asyncio.run(_go())
    if as_json:
        typer.echo(
            json.dumps(
                [{"provider": n, "healthy": h, "detail": d} for n, h, d in rows],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for name, healthy, detail in rows:
            mark = "ok  " if healthy else "FAIL"
            color = typer.colors.GREEN if healthy else typer.colors.RED
            typer.secho(f"{mark} {name:<16} {detail}", fg=color)
        for line in warnings:
            typer.secho(line, fg=typer.colors.YELLOW)
    if any(not healthy for _, healthy, _ in rows):
        raise typer.Exit(code=1)


# -- poieo config -------------------------------------------------------------
#
# `check` asks whether an endpoint is up. These ask what it *serves*, and what
# this project decided to do with that -- two questions close enough together
# to be confused, so: check probes, config reads the file, config models asks
# the endpoints for their catalogue.


def _configured() -> "tuple[Path, Any]":
    """The project here and the binding it names, or a refusal in the usual words."""
    marker = _project_file(None)
    project = load_project(marker)
    if not project.binding:
        _fail(f"{marker} names no binding; add `binding: <file>` to it")
    path = project.resolve_path(project.binding)
    return path, load_binding(path)


@config_app.callback(invoke_without_command=True)
@_guarded
def config(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON."),
) -> None:
    """What this project is bound to: its endpoints, its default, its roles.

    Reads files and opens no socket. `poieo config models` is the one that
    asks the endpoints themselves.
    """
    if ctx.invoked_subcommand is not None:
        return
    path, spec = _configured()

    # One report, two renderings, as `validate` does: the facts are gathered
    # once so the JSON an agent parses cannot drift from the lines a person
    # reads.
    report: dict[str, Any] = {
        "binding": {"name": spec.name, "path": str(path)},
        "providers": {name: {"type": p.type, "base_url": p.base_url} for name, p in spec.providers.items()},
        "default": spec.target("default"),
        "roles": {role: spec.target(role) for role in sorted(spec.roles)},
    }
    if as_json:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    typer.echo(f"binding    {path}  ({spec.name})")
    typer.echo("")
    typer.echo("providers")
    for name, provider in spec.providers.items():
        # An endpoint with no address is one whose SDK knows where it lives.
        typer.echo(f"  {name:<12}{provider.type:<20}{provider.base_url or ''}".rstrip())
    typer.echo("")
    typer.echo(f"default    {report['default'] or '(the binding names none)'}")
    if report["roles"]:
        typer.echo("roles")
        for role, target in report["roles"].items():
            typer.echo(f"  {role:<12}{target or '(unresolvable)'}")
    else:
        # Not a defect -- one model for everything is a legitimate binding --
        # but it is the thing most worth knowing you *could* do.
        typer.echo("roles      none; every step runs on the default")
        typer.echo("           `poieo config models` lists what else is here")


@config_app.command("models")
@_guarded
def config_models(
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON."),
) -> None:
    """What each declared endpoint serves right now.

    Asked live rather than remembered, because a list written down a month ago
    is a list that has since gone wrong -- and a model named from memory fails
    at 3am, which is the whole thing poieo is built not to do.
    """
    _, spec = _configured()
    names = list(spec.providers)

    async def _go() -> list[tuple[str, ...]]:
        # All at once: two endpoints asked in single file is two timeouts on a
        # laptop where neither is running.
        return list(
            await asyncio.gather(
                *(engines.models_for(p.type, p.base_url, p.api_key_env) for p in spec.providers.values())
            )
        )

    served = dict(zip(names, asyncio.run(_go())))
    in_use = spec.roles_by_target()

    report = {
        name: {
            "type": spec.providers[name].type,
            "base_url": spec.providers[name].base_url,
            "reachable": bool(served[name]),
            "models": list(served[name]),
        }
        for name in names
    }
    if as_json:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    for name in names:
        provider = spec.providers[name]
        models = served[name]
        if models:
            detail = provider.base_url or ""
        elif not engines.askable(provider.type):
            # `mock` answers from its own file; a backend a caller registered
            # has no listing convention. Neither is a failure to report.
            detail = "nothing to ask -- it answers from the binding"
        else:
            detail = "no answer"
        typer.secho(f"{name:<12}{detail}".rstrip(), bold=True)
        for model in models:
            # Every role it answers for, not one of them: a model two roles
            # point at is the ordinary reason to name roles at all.
            roles = ", ".join(in_use.get(f"{name}/{model}", ()))
            # Padded only when there is something to line up against, so an
            # unspoken-for model is exactly its own name. The trailing gap is
            # unconditional: an id longer than the column still needs air
            # before its role, and real Ollama tags run past 44 easily.
            typer.echo(f"  {model:<44}  {roles}" if roles else f"  {model}")
        typer.echo("")


@config_app.command("add")
@_guarded
def config_add(
    url: str = typer.Argument(
        "",
        help="An engine's address, if it is not on one of this machine's usual ports.",
    ),
    name: str = typer.Option("", "--name", help="What to call it in the file. Defaults to what it says it is."),
    key_env: str = typer.Option(
        "",
        "--key-env",
        help="The variable its key is read from. A name, never the key itself.",
    ),
) -> None:
    """Look for engines again, and declare any that is not already here.

    Detection otherwise runs once, at `init`. Install Ollama next week and the
    binding has never heard of it -- this is how it does, and it is the same
    look `init` took.

    **With an address**, it asks that one instead. Detection knows four ports on
    *this* machine, and an inference server is routinely somewhere else -- one
    on 8001 because 8000 was taken, an Ollama on the desktop under the desk, a
    shared box in an office. Which backend it is comes from asking rather than
    from a flag: both listing shapes are tried, and the one that answers says.

    Only adds. An endpoint already declared is left exactly as it is, since
    somebody may have pointed it at another port; and the default never moves,
    because declaring a model and choosing one are different decisions.
    """
    path, _ = _configured()
    if key_env and not url:
        # The four ports detection looks at on this machine are not endpoints a
        # key opens, and there would be no saying which of them it was meant
        # for. Silently ignoring it left somebody believing they had declared a
        # keyed endpoint they had not.
        _fail("--key-env names the key for one address; pass the address too")
    if url:
        # An address with a typo in it is not an address that answered nothing.
        if (unaskable := engines.unaskable(url)) is not None:
            _fail(unaskable)
        engine = asyncio.run(engines.ask(url, key_env or None))
        if engine is None:
            # Only on the way out, and never as a precondition. The key may
            # well live in the environment the daemon or a wrapper runs under
            # rather than this shell, and recording its name in a file somebody
            # commits is a perfectly good reason to run this here -- so an
            # endpoint that lists without one still declares.
            #
            # But an endpoint that wants a key answers 401 to a listing, which
            # detection reads as silence. "Nothing usable answered" alone is a
            # true sentence about the wrong problem, and has the reader retyping
            # an address that was right.
            if key_env and not os.environ.get(key_env):
                _fail(
                    f"nothing usable answered at {url}, and ${key_env} is not set here -- "
                    f"if that endpoint wants a key, it was asked without one"
                )
            _fail(f"nothing usable answered at {url} -- no listing, or one with no models on it")
        if name:
            engine = replace(engine, key=name)
        # By name *and* by address, through the one rule the board asks too --
        # so the same press cannot be refused in the browser and accepted here.
        if (why := already(path, engine)) is not None:
            _fail(why)
        found = [engine]
    else:
        found = engines.detect()

    added = declare(path, found)
    if not added:
        # Say where it looked, so "nothing new" is an answer rather than a
        # shrug. An engine already declared is not news.
        seen = ", ".join(engine.known_as for engine in found) or "nothing"
        typer.echo(f"nothing new -- this machine answers with: {seen}")
        return

    by_key = {engine.key: engine for engine in found}
    _ok(f"declared {', '.join(added)} in {path}")
    for key in added:
        engine = by_key[key]
        typer.echo("")
        # The key leads because it is what `config use` takes back, but what
        # the thing *is* has to be here too: `vllm` is the name detection
        # picked for a port vLLM and SGLang share, and only the server can say
        # which of them just got declared.
        typer.echo(f"{key:<12}{engine.known_as:<16}{engine.base_url or ''}".rstrip())
        for model in engine.models:
            typer.echo(f"  {model}")
    first = by_key[added[0]]
    typer.echo("")
    typer.echo(f"to use one:  poieo config use {first.key}/{first.models[0]} --role <name>")


# How many names a refusal offers back. The check behind it is uncapped, and a
# hosted router serves several hundred -- printed whole, the one useful line of
# a refusal scrolls off the top of the terminal.
MODEL_LIST = 12


@config_app.command("use")
@_guarded
def config_use(
    target: str = typer.Argument(..., help="Which model, as provider/model -- exactly as `poieo config` prints it."),
    role: str = typer.Option(
        "default",
        "--role",
        help="Bind this role instead of the default. A graph that names the "
        "role uses it; every other step is unaffected.",
    ),
) -> None:
    """Point a role at a different model.

    One edit to the binding file, keeping everything else in it -- comments
    included -- exactly as it was. Refuses a provider the binding does not
    declare, and a model the endpoint says it does not serve.
    """
    path, spec = _configured()

    try:
        provider, model = split_ref(target)
    except BindingError as exc:
        _fail(str(exc))

    # Empty covers both "not declared" -- point_at refuses that below, in one
    # wording -- and "declared but silent".
    served: tuple[str, ...] = ()
    if provider in spec.providers:
        # Best effort, and only when the endpoint answers: a laptop with its
        # server switched off still gets to edit its own config. But a model
        # named from memory is the typo this whole pair exists to prevent, so
        # when there *is* an answer it is believed.
        declared = spec.providers[provider]
        # Uncapped: this is a membership check, not a listing. Asked with the
        # listing's cap it refuses everything a hosted router serves past the
        # first forty, and then prints those forty as the whole catalogue.
        served = asyncio.run(engines.models_for(declared.type, declared.base_url, declared.api_key_env, limit=None))
        if served and model not in served:
            # Says it is a sample when it is one. Printing a truncated list as
            # though it were the catalogue is what the capped check did.
            rest = len(served) - MODEL_LIST
            more = f", and {rest} more" if rest > 0 else ""
            _fail(f"'{provider}' does not serve '{model}'. It has: {', '.join(served[:MODEL_LIST])}{more}")

    point_at(path, role, provider, model)

    named = "default" if role == "default" else f"role '{role}'"
    _ok(f"{named} now uses {provider}/{model}")
    typer.echo(f"           {path}")
    if provider in spec.providers and not served:
        # Said out loud rather than implied: silence from an endpoint is not
        # the same as its agreement.
        typer.echo(f"note       '{provider}' did not answer, so the model name could not be checked")


def _unreviewable(cards: "list[CardSpec]") -> set[str]:
    """Which of these work somewhere git cannot track.

    One `git rev-parse` per card, asked all at once rather than one after
    another: on Windows a subprocess is most of a tenth of a second, and a
    listing of ten tasks is what a person types to see the board quickly.
    """

    async def _ask() -> list[bool]:
        return list(
            await asyncio.gather(
                *(
                    asyncio.to_thread(
                        Workspace(
                            card.folder_path(),
                            card.slug,
                            layout_for(card.dir).worktrees(),
                        ).available
                    )
                    for card in cards
                    if card.folder
                )
            )
        )

    with_folders = [card for card in cards if card.folder]
    if not with_folders:
        return set()
    answers = asyncio.run(_ask())
    return {card.folder for card, ok in zip(with_folders, answers) if not ok}


DEFAULT_BOARD_PORT = 8484


def _board(port: int, host: str = "127.0.0.1") -> "httpx.Client":
    """A client for the daemon's board.

    The one thing in this CLI that needs poieo to already be running: a
    question is state the daemon holds, and answering it sets a chain of tasks
    going in that process.
    """
    import httpx

    return httpx.Client(base_url=f"http://{host}:{port}", timeout=10.0)


def _ask_board(port: int, method: str, path: str, *, host: str = "127.0.0.1", **kwargs) -> "Any":
    """One call to the board, with its two ordinary failures spelled out."""
    import httpx

    try:
        with _board(port, host) as client:
            reply = client.request(method, path, **kwargs)
    except httpx.HTTPError:
        _fail(f"no poieo daemon answering on port {port}. Start one with `poieo daemon`, or name its port with --port")
    if reply.status_code >= 400:
        body = {}
        try:
            body = reply.json()
        except ValueError:
            pass
        said = body.get("error") or f"the board answered {reply.status_code}"
        offered = body.get("choices")
        if offered:
            said = f"{said}. It is asking for one of: {'/'.join(offered)}"
        _fail(said)
    return reply.json()


def _this_board() -> str:
    """The name the running daemon knows this project by."""
    return _daemon_config(None).display_name


@app.command(rich_help_panel=BOARD)
@_guarded
def asking(
    port: int = typer.Option(DEFAULT_BOARD_PORT, "--port", help="The daemon's board port."),
    host: str = typer.Option("127.0.0.1", "--host", help="Where that daemon is listening, if not this machine."),
) -> None:
    """What the tasks are waiting for you to decide.

    A `confirm` node ends its run with a question rather than doing something
    that cannot be undone. Until it is answered, nothing downstream of it runs.
    """
    body = _ask_board(port, "GET", "/api/tasks", host=host)
    waiting = [row for row in body.get("tasks", []) if row.get("asking")]
    if not waiting:
        typer.echo("nothing is waiting on you")
        return
    for row in waiting:
        question = row["asking"]
        typer.secho(f"{row['name']}", fg=typer.colors.CYAN, nl=False)
        typer.echo(f"  [{'/'.join(question['choices'])}]")
        for line in question["question"].splitlines():
            typer.echo(f"    {line}")
    typer.echo("\nanswer one with: poieo answer <task> <choice>")


@app.command(rich_help_panel=BOARD)
@_guarded
def answer(
    task: str = typer.Argument(..., help="The task that is waiting."),
    choice: str = typer.Argument(..., help="One of the answers it offered."),
    port: int = typer.Option(DEFAULT_BOARD_PORT, "--port", help="The daemon's board port."),
    host: str = typer.Option("127.0.0.1", "--host", help="Where that daemon is listening, if not this machine."),
) -> None:
    """Answer a question a task stopped to ask.

    What happens next is the card's `then:`, which has been held back since the
    run ended -- so this is the step that lets the rest of the chain run.
    """
    body = _ask_board(
        port,
        "POST",
        f"/api/tasks/{_this_board()}/{task}/answer",
        host=host,
        json={"choice": choice},
    )
    _ok(f"{task}: {body.get('answer', choice)}")


@app.command(rich_help_panel=BOARD)
@_guarded
def tasks(
    target: Optional[Path] = typer.Argument(None, help="A tasks folder, or a config file [default: the project's]."),
) -> None:
    """The tasks on the board, when each next runs, and what it last said.

    This used to have a second half, `poieo flows`, which loaded every graph
    and binding to print the same roster with the models resolved. `validate`
    already answers that for one task and `config` for the project, and the
    one thing only it said -- that a task's work cannot be reviewed or undone
    -- belongs here, where a person actually looks.
    """
    if target is not None and target.is_dir():
        folder = target
    else:
        # Discovery only fills silence: named config, else the project's.
        source = target if target is not None else _project_file(None)
        config = load_config(source)
        if not config.cards:
            _fail(f"{source} names no tasks folder")
        folder = config.resolve_path(config.cards)
    items = load_cards(folder)

    if not items:
        typer.echo("(no tasks)")
        return
    unreviewable = _unreviewable(items)
    for card in items:
        task, _ = expand(card)
        state = "on " if task.enabled else "off"
        typer.echo(f"[{state}] {card.slug:<20} {task.trigger.build().describe:<24} {card.folder_path()}")
        # "isolated", never the image: naming it is licensed in configuration
        # and in errors, not in a listing.
        boxed = " · isolated" if card.isolation else ""
        typer.echo(f"        {card.name}{boxed}")
        last = read_journal(card.journal_path(), limit=1).splitlines()[-1]
        typer.echo(f"        {last}")
        if card.folder in unreviewable:
            # Degraded, not broken: it still runs tonight. But principle 7's
            # moment -- the user's own files are about to change -- is exactly
            # this one, and it must not be found out afterwards.
            typer.secho(
                f"        note: changes in {card.folder_path()} can't be reviewed or undone",
                fg=typer.colors.YELLOW,
            )


@app.command(rich_help_panel=BOARD)
@_guarded
def note(
    task_path: Path = typer.Argument(..., help="Task YAML/JSON file."),
    text: str = typer.Argument(..., help="What you want it to do differently."),
) -> None:
    """Tell a task something. It reads this before its next run."""
    task = load_card(task_path)
    append_journal(task.journal_path(), "you", text, title=task.name)
    _ok(f"noted in {task.journal_path()}")


def _memory_target(path: "Path | None") -> "tuple[CardSpec | None, Path]":
    """The card being asked about, and the project it belongs to.

    Always the project's *root*, because that is where the memory is: `poieo
    memory` from inside `tasks/` and from above must not disagree.
    """
    if path is None:
        return None, layout_for().root
    task = _load_card(path) if path.is_file() else None
    if task is None and not path.is_dir():
        _fail(f"no such folder or card: {path}")
    return task, layout_for(task.dir if task is not None else path).root


@app.command(rich_help_panel=AFTER)
@_guarded
def memory(
    path: Optional[Path] = typer.Argument(None, help="A card, or a folder in the project [default: here]."),
) -> None:
    """What this project remembers, and what a task would be shown.

    Read-only on purpose: authoring belongs to the editor and git, and the
    lookup machinery rebuilds itself, so there is nothing here to run.
    """
    task, project = _memory_target(path)

    report = memory_report(project)
    if report is None:
        typer.echo(f"no memory here yet. `poieo init` here starts one at {layout_for(project).longterm()}")
        return

    typer.echo(f"page       {report['page_chars']} characters (budget {report['page_budget']})")
    typer.echo(f"learned    {report['kept']} kept, {report['set_aside']} set aside")
    typer.echo(f"lookup     {report['lookup']}")
    for one, other in report["disagreements"]:
        typer.echo(f"disagree     {one} <-> {other}")
    for line in report["second_look"]:
        typer.echo(f"second look  {line}")
    accounting = report.get("accounting")
    if accounting:
        typer.echo(
            f"kept in mind  {accounting['runs_used']} of {accounting['runs_shown']} "
            "recent runs used what they were shown"
        )
        for slug, count in accounting["unused"]:
            typer.echo(f"unused       {slug} (shown {count} times, used never)")
    suggestion = last_suggestion(project)
    if suggestion:
        typer.echo(f"the last pass suggests: {suggestion}")
    if task is not None:
        typer.echo("")
        typer.echo(f"what {task.slug} will be shown on its next run:")
        typer.echo(read_memory(project, task, preview=True) or "(nothing)")


@app.command(rich_help_panel=AFTER)
@_guarded
def learn(
    path: Optional[Path] = typer.Argument(None, help="A card, or a folder in the project [default: here]."),
    binding: Optional[Path] = typer.Option(
        None, "--binding", "-b", help="Binding whose `learner` role reads the night."
    ),
) -> None:
    """Read what has run, and write down what stays true."""
    task, project = _memory_target(path)

    binding, _ = _find_binding(binding, task, path.parent if path is not None else None)
    if binding is None:
        _fail(_NO_BINDING)
    spec = load_binding(binding)

    if not keeps_memory(project):
        typer.echo(f"no memory here yet. `poieo init` here starts one at {layout_for(project).longterm()}")
        return

    async def _go():
        async with ProviderPool(spec) as pool:
            return await run_learning_pass(project, spec, pool)

    result = asyncio.run(_go())
    if result is None:
        typer.echo("nothing new to learn from")
        return
    if result.error is not None:
        _fail(f"the pass failed and will reread next time: {result.error}")
    typer.echo(f"read       {result.read} record{'s' if result.read != 1 else ''}")
    typer.echo(f"kept       {', '.join(result.kept) or '(nothing -- most nights teach nothing)'}")
    if result.set_aside:
        typer.echo(f"set aside  {', '.join(result.set_aside)}")
    if result.dropped:
        typer.echo(
            f"let go     {len(result.dropped)} suggestion"
            f"{'s' if len(result.dropped) != 1 else ''} (memory/cache/learning.jsonl says why)"
        )


@app.command(hidden=True)
@_guarded
def eject(
    task_path: Path = typer.Argument(..., help="Task YAML/JSON file."),
    to: Optional[Path] = typer.Option(
        None, "--to", help="Where to write the graph [<task>.graph.yaml, beside the card]."
    ),
) -> None:
    """Write out the graph a task stands for, and point the task at it."""
    task = load_card(task_path)

    if task.graph:
        _fail(f"{task_path} already names a graph: {task.graph}")
    # Beside the card, under its name: `load_cards` tells the two apart by
    # shape, so one folder holds both.
    target = to or (task.dir / f"{task.slug}.graph.yaml")
    if target.exists():
        _fail(f"{target} already exists")

    graph = build_graph(task)
    document = graph.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")

    kept: dict[str, Any] = {"name": task.name, "folder": task.folder}
    if task.every is not None:
        kept["every"] = task.every
    if task.at is not None:
        kept["at"] = task.at
    if task.binding:
        kept["binding"] = task.binding
    if not task.enabled:
        kept["enabled"] = False
    if task.isolation is not None:
        # Where the work may run describes the task, not the node the graph
        # took over -- so it stays on the card the graph is run through.
        kept["isolation"] = task.isolation.model_dump(mode="json", exclude_none=True)
    try:
        named = Path(os.path.relpath(target, task.dir)).as_posix()
    except ValueError:  # a different drive on Windows: no relative path exists
        named = target.as_posix()
    kept["graph"] = named
    task_path.write_text(yaml.safe_dump(kept, sort_keys=False, allow_unicode=True), encoding="utf-8")

    _ok(f"wrote {target}")
    typer.echo(f"{task_path} now names it (comments in it were not preserved)")
    typer.echo(
        "the graph reads {{ input.journal }}, which the task supplies -- run it "
        f"through '{task_path}', or pass --set journal=..."
    )


def _resolve_store(store: "Path | None") -> Path:
    """Flag, then the project's ``store:``, then ``./runs``."""
    if store is not None:
        return store
    return layout_for().runs()


@runs_app.command("list")
@_guarded
def runs_list(
    store: Optional[Path] = typer.Option(
        None,
        "--store",
        help="Where the run history lives [default: the project's runs/].",
    ),
    limit: int = typer.Option(20, "--limit", "-n"),
    task: Optional[str] = typer.Option(None, "--task"),
    as_json: bool = typer.Option(False, "--json", help="Print the rows as JSON."),
) -> None:
    """List recent runs, newest first."""
    store = _resolve_store(store)
    rows = RunStore(store).list_runs(limit=limit, task=task)
    if as_json:
        # JSON stays JSON even when empty -- an agent parses, never greps.
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        # Name where we looked: an empty answer should still orient the user.
        typer.echo(f"no runs recorded under {store}")
        return
    for row in rows:
        color = typer.colors.GREEN if row.get("status") == "completed" else typer.colors.RED
        usage = row.get("usage") or {}
        typer.secho(
            f"{row.get('run_id'):<26} {row.get('status'):<10} "
            f"{row.get('task', '-'):<16} {row.get('graph', '-'):<20} "
            f"steps={row.get('steps')} out={usage.get('output_tokens', 0)}",
            fg=color,
        )


@runs_app.command("show")
@_guarded
def runs_show(
    run_id: str = typer.Argument(..., help="Run id from `poieo runs list`."),
    store: Optional[Path] = typer.Option(
        None,
        "--store",
        help="Where the run history lives [default: the project's runs/].",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print raw events."),
) -> None:
    """Replay one run's event log."""
    store = _resolve_store(store)
    events = list(RunStore(store).events(run_id))
    if not events:
        _fail(f"no events for run '{run_id}' under {store}")
    if as_json:
        for event in events:
            typer.echo(json.dumps(event, ensure_ascii=False))
        return
    for event in events:
        data = event.get("data") or {}
        head = f"{event['at']}  {event['type']:<14}"
        if event.get("node_id"):
            head += f" {event['node_id']}"
        typer.echo(head)
        for key in ("binding", "model", "next", "condition", "label", "error", "reason"):
            if key in data:
                value = data[key]
                typer.echo(f"    {key}: {'(end)' if value is None else value}")
        if "output" in data:
            text = data["output"]
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False)
            typer.echo(f"    output: {text[:400]}")


if __name__ == "__main__":  # pragma: no cover
    app()
