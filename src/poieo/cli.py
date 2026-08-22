"""Command line front end.

Every command is a thin wrapper over the library, so the web editor that comes
later can call the same functions without shelling out.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

import typer
import yaml

# Model output is arbitrary Unicode; legacy Windows console codepages (cp949,
# cp1252, ...) cannot encode all of it and would crash every `poieo run` that
# prints a fancy dash. Reconfigure rather than crash.
for _stream in (sys.stdout, sys.stderr):
    if _stream and _stream.encoding and _stream.encoding.lower() not in ("utf-8", "utf8"):
        _stream.reconfigure(errors="replace")

from . import __version__
from .binding import load_binding
from .daemon import Daemon, load_config, load_flows
from .errors import PoieoError
from .graph import GraphSpec, load_graph
from .providers import ProviderPool
from .runtime.executor import execute, preflight
from .store import NullStore, RunStore
from .task import (
    append_journal,
    build_graph,
    expand,
    is_task_file,
    load_task,
    load_tasks,
    read_journal,
)
from .editor import render_editor
from .viewer import mermaid_source, render_page

app = typer.Typer(
    name="poieo",
    help="Run logical LLM workflows against physical models you bind separately.",
    no_args_is_help=True,
    add_completion=False,
)
runs_app = typer.Typer(name="runs", help="Inspect past runs.", no_args_is_help=True)
app.add_typer(runs_app)

err = typer.style


def _fail(message: str) -> None:
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


@app.command()
def version() -> None:
    """Print the poieo version."""
    typer.echo(f"poieo {__version__}")


def _load_spec(path: Path) -> GraphSpec:
    """Load a graph, or the graph a task file stands for."""
    if not is_task_file(path):
        return load_graph(path)
    task = load_task(path)
    if task.graph:
        return load_graph(task.resolve(task.graph))
    return build_graph(task)


def _task_payload(path: Path) -> dict[str, Any]:
    """What a task's generated graph expects in its input, beyond the user's."""
    if not is_task_file(path):
        return {}
    return {"journal": read_journal(load_task(path).journal_path())}


@app.command()
def validate(
    graph_path: Path = typer.Argument(..., help="Graph or task YAML/JSON file."),
    binding: Optional[Path] = typer.Option(
        None, "--binding", "-b", help="Also check every role resolves in this binding."
    ),
) -> None:
    """Parse a graph or task (and optionally a binding) and report problems."""
    try:
        graph = _load_spec(graph_path)
    except PoieoError as exc:
        _fail(str(exc))

    typer.echo(f"graph      {graph.name} v{graph.version}  ({len(graph.nodes)} nodes)")
    typer.echo(f"entry      {graph.entry}")
    typer.echo(f"roles      {', '.join(sorted(graph.roles())) or '(none)'}")

    if binding:
        try:
            spec = load_binding(binding)
            preflight(graph, spec)
        except PoieoError as exc:
            _fail(str(exc))
        typer.echo(f"binding    {spec.name}")
        for role in sorted(graph.roles()):
            typer.echo(f"           {spec.resolve(role).describe()}")
    _ok("valid")


@app.command()
def show(
    graph_path: Path = typer.Argument(..., help="Graph or task YAML/JSON file."),
    mermaid: bool = typer.Option(False, "--mermaid", help="Emit a mermaid flowchart."),
) -> None:
    """Print what a graph -- or what a task expands to -- looks like."""
    try:
        graph = _load_spec(graph_path)
    except PoieoError as exc:
        _fail(str(exc))

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
            if node.type in ("llm", "agent")
            else f"{len(node.branches)} branch(es)"
        )
        typer.echo(f" {marker} {node.id:<16} {node.type:<7} {detail}")
        for branch in node.branches:
            typer.echo(f"      when {branch.when}  ->  {branch.to or '(end)'}")
        if node.type == "router":
            typer.echo(f"      default        ->  {node.default or '(end)'}")
        elif node.next:
            typer.echo(f"      next           ->  {node.next}")


@app.command()
def view(
    graph_paths: list[Path] = typer.Argument(..., help="One or more graph files."),
    binding: Optional[Path] = typer.Option(
        None, "--binding", "-b", help="Show which model each role resolves to."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Where to write the page [.poieo/views/<name>.html]."
    ),
    serve: bool = typer.Option(
        False, "--serve", help="Serve the page over http instead of just writing it."
    ),
    port: int = typer.Option(8765, "--port", help="Port for --serve."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface for --serve."),
) -> None:
    """Render graphs as a browsable HTML page."""
    try:
        graphs = [_load_spec(path) for path in graph_paths]
        spec = load_binding(binding) if binding else None
    except PoieoError as exc:
        _fail(str(exc))

    title = graphs[0].name if len(graphs) == 1 else f"{len(graphs)} workflows"
    page = render_page(graphs, spec, title=title)

    target = output or Path(".poieo/views") / f"{graphs[0].name}.html"
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
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=directory
    )
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
            capture_output=True, text=True, timeout=15,
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


@app.command()
def edit(
    graph_path: Path = typer.Argument(..., help="Graph file to edit."),
    binding: Optional[Path] = typer.Option(
        None, "--binding", "-b", help="Show which model each role resolves to."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Where to write the editor page."
    ),
    save_via: str = typer.Option(
        "auto", "--save-via",
        help="How the page saves: auto | jupyter | none (download/copy only).",
    ),
    token: Optional[str] = typer.Option(None, "--token", help="Jupyter token."),
    root: Optional[Path] = typer.Option(
        None, "--jupyter-root", help="Jupyter's root_dir, for building the save path."
    ),
    serve: bool = typer.Option(False, "--serve", help="Serve the page over http."),
    port: int = typer.Option(8765, "--port"),
    host: str = typer.Option("127.0.0.1", "--host"),
) -> None:
    """Open a graph in the drag-and-drop canvas editor."""
    if is_task_file(graph_path):
        # The editor saves back over what it opened, and a task is not a graph.
        _fail(f"{graph_path} is a task; run 'poieo eject' first, then edit the graph")
    try:
        graph = load_graph(graph_path)
        spec = load_binding(binding) if binding else None
    except PoieoError as exc:
        _fail(str(exc))

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
    target = output or Path(".poieo/views") / f"{graph.name}-edit.html"
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


@app.command()
def run(
    graph_path: Path = typer.Argument(..., help="Graph or task YAML/JSON file."),
    binding: Path = typer.Option(..., "--binding", "-b", help="Binding YAML/JSON file."),
    input_json: Optional[str] = typer.Option(
        None, "--input", "-i", help="Run payload as JSON, or @file.json."
    ),
    set_: list[str] = typer.Option(
        [], "--set", "-s", help="Payload override, key=value. Repeatable."
    ),
    store: Path = typer.Option(Path(".poieo"), "--store", help="Run-log directory."),
    no_log: bool = typer.Option(False, "--no-log", help="Do not write a run log."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Execute a graph, or a task, once."""
    _setup_logging(verbose)
    try:
        graph = _load_spec(graph_path)
        spec = load_binding(binding)
    except PoieoError as exc:
        _fail(str(exc))

    payload = {**_task_payload(graph_path), **_parse_input(input_json, set_)}
    run_store = NullStore() if no_log else RunStore(store)

    async def _go():
        async with ProviderPool(spec) as pool:
            return await execute(graph, spec, pool, run_store, input=payload)

    try:
        result = asyncio.run(_go())
    except PoieoError as exc:
        _fail(str(exc))

    if as_json:
        typer.echo(json.dumps(result.__dict__, indent=2, ensure_ascii=False, default=str))
    else:
        color = typer.colors.GREEN if result.status == "completed" else typer.colors.RED
        typer.secho(f"{result.status}  {result.run_id}", fg=color)
        typer.echo(f"path       {' -> '.join(result.path)}")
        typer.echo(
            f"tokens     in={result.usage['input_tokens']} "
            f"out={result.usage['output_tokens']}"
        )
        if result.error:
            typer.secho(f"error      {result.error}", fg=typer.colors.RED)
        for node_id, value in result.outputs.items():
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            typer.echo(f"\n--- {node_id} ---\n{rendered}")

    if result.status != "completed":
        raise typer.Exit(code=1)


@app.command()
def daemon(
    config_path: Path = typer.Argument(..., help="Daemon config YAML/JSON file."),
    once: bool = typer.Option(
        False, "--once", help="Fire each flow a single time, then exit."
    ),
    flow: Optional[str] = typer.Option(
        None, "--flow", help="Run only this flow from the config."
    ),
    port: int = typer.Option(8484, "--port", help="Web observation UI port."),
    no_web: bool = typer.Option(False, "--no-web", help="Disable the web UI."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start the resident scheduler and keep flows running."""
    _setup_logging(verbose)
    try:
        config = load_config(config_path)
    except PoieoError as exc:
        _fail(str(exc))

    if flow:
        matching = [f for f in config.flows if f.name == flow]
        if not matching:
            _fail(f"no flow named '{flow}' in {config_path}")
        config.flows = matching

    if once:
        # A single pass per flow: cap iterations and make interval flows fire
        # immediately instead of waiting out their first period.
        for spec in config.flows:
            spec.trigger.max_iterations = 1
            spec.trigger.run_at_start = True
            if spec.trigger.type == "manual":
                spec.trigger = spec.trigger.model_copy(update={"type": "loop"})

    try:
        results = asyncio.run(
            Daemon(config, web_port=None if no_web else port).serve()
        )
    except PoieoError as exc:
        _fail(str(exc))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        raise typer.Exit(code=130)

    failed = [r for r in results if r.status != "completed"]
    if once:
        typer.echo(f"\n{len(results)} run(s), {len(failed)} not completed")
    if failed:
        raise typer.Exit(code=1)


@app.command("check")
def check_providers(
    binding: Path = typer.Option(..., "--binding", "-b", help="Binding YAML/JSON file."),
) -> None:
    """Probe every provider declared in a binding."""
    try:
        spec = load_binding(binding)
    except PoieoError as exc:
        _fail(str(exc))

    async def _go() -> list[tuple[str, bool, str]]:
        rows: list[tuple[str, bool, str]] = []
        async with ProviderPool(spec) as pool:
            for name in spec.providers:
                try:
                    healthy, detail = await pool.get(name).health()
                except PoieoError as exc:
                    healthy, detail = False, str(exc)
                rows.append((name, healthy, detail))
        return rows

    rows = asyncio.run(_go())
    for name, healthy, detail in rows:
        mark = "ok  " if healthy else "FAIL"
        color = typer.colors.GREEN if healthy else typer.colors.RED
        typer.secho(f"{mark} {name:<16} {detail}", fg=color)
    if any(not healthy for _, healthy, _ in rows):
        raise typer.Exit(code=1)


@app.command()
def flows(
    config_path: Path = typer.Argument(..., help="Daemon config YAML/JSON file."),
) -> None:
    """List the flows a daemon config would run, with their triggers and bindings."""
    try:
        config = load_config(config_path)
        loaded = load_flows(config, enabled_only=False)
    except PoieoError as exc:
        _fail(str(exc))

    for item in loaded:
        state = "on " if item.spec.enabled else "off"
        trigger = item.spec.trigger.build().describe
        typer.echo(
            f"[{state}] {item.spec.name:<20} {item.graph.name:<20} "
            f"{trigger:<24} binding={item.binding.name}"
        )
        for role in sorted(item.graph.roles()):
            typer.echo(f"        {item.binding.resolve(role).describe()}")


@app.command()
def tasks(
    target: Path = typer.Argument(..., help="Daemon config file, or a tasks folder."),
) -> None:
    """List the task cards in a folder, or the ones a daemon config would run."""
    try:
        if target.is_dir():
            folder = target
        else:
            config = load_config(target)
            if not config.tasks:
                _fail(f"{target} names no tasks folder")
            folder = config.resolve_path(config.tasks)
        items = load_tasks(folder)
    except PoieoError as exc:
        _fail(str(exc))

    if not items:
        typer.echo("(no tasks)")
        return
    for task in items:
        flow, _ = expand(task)
        state = "on " if task.enabled else "off"
        typer.echo(
            f"[{state}] {task.slug:<20} {flow.trigger.build().describe:<24} "
            f"{task.folder_path()}"
        )
        typer.echo(f"        {task.name}")
        last = read_journal(task.journal_path(), limit=1).splitlines()[-1]
        typer.echo(f"        {last}")


@app.command()
def note(
    task_path: Path = typer.Argument(..., help="Task YAML/JSON file."),
    text: str = typer.Argument(..., help="What you want it to do differently."),
) -> None:
    """Tell a task something. It reads this before its next piece of work."""
    try:
        task = load_task(task_path)
    except PoieoError as exc:
        _fail(str(exc))
    append_journal(task.journal_path(), "you", text, title=task.name)
    _ok(f"noted in {task.journal_path()}")


@app.command()
def eject(
    task_path: Path = typer.Argument(..., help="Task YAML/JSON file."),
    to: Optional[Path] = typer.Option(
        None, "--to", help="Where to write the graph [../graphs/<task>.yaml]."
    ),
) -> None:
    """Write out the graph a task stands for, and point the task at it."""
    try:
        task = load_task(task_path)
    except PoieoError as exc:
        _fail(str(exc))

    if task.graph:
        _fail(f"{task_path} already names a graph: {task.graph}")
    target = to or (task.dir.parent / "graphs" / f"{task.slug}.yaml")
    if target.exists():
        _fail(f"{target} already exists")

    graph = build_graph(task)
    document = graph.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude_defaults=True
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    kept: dict[str, Any] = {"name": task.name, "folder": task.folder}
    if task.every is not None:
        kept["every"] = task.every
    if task.at is not None:
        kept["at"] = task.at
    if task.binding:
        kept["binding"] = task.binding
    if not task.enabled:
        kept["enabled"] = False
    try:
        named = Path(os.path.relpath(target, task.dir)).as_posix()
    except ValueError:  # a different drive on Windows: no relative path exists
        named = target.as_posix()
    kept["graph"] = named
    task_path.write_text(
        yaml.safe_dump(kept, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    _ok(f"wrote {target}")
    typer.echo(f"{task_path} now names it (comments in it were not preserved)")
    typer.echo(
        "the graph reads {{ input.journal }}, which the task supplies -- run it "
        f"through '{task_path}', or pass --set journal=..."
    )


@runs_app.command("list")
def runs_list(
    store: Path = typer.Option(Path(".poieo"), "--store", help="Run-log directory."),
    limit: int = typer.Option(20, "--limit", "-n"),
    flow: Optional[str] = typer.Option(None, "--flow"),
) -> None:
    """List recent runs, newest first."""
    rows = RunStore(store).list_runs(limit=limit, flow=flow)
    if not rows:
        typer.echo("no runs recorded")
        return
    for row in rows:
        color = typer.colors.GREEN if row.get("status") == "completed" else typer.colors.RED
        usage = row.get("usage") or {}
        typer.secho(
            f"{row.get('run_id'):<26} {row.get('status'):<10} "
            f"{row.get('flow','-'):<16} {row.get('graph','-'):<20} "
            f"steps={row.get('steps')} out={usage.get('output_tokens', 0)}",
            fg=color,
        )


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="Run id from `poieo runs list`."),
    store: Path = typer.Option(Path(".poieo"), "--store", help="Run-log directory."),
    as_json: bool = typer.Option(False, "--json", help="Print raw events."),
) -> None:
    """Replay one run's event log."""
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
