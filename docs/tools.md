# Tools — the hands

`src/poieo/tools/` — `__init__.py`, `files.py`, `shell.py`, `notes.py`, `docker.py`

An agent node hands the model tool definitions and executes what it asks for.
A node never touches the filesystem or a subprocess directly: it hands
`ToolCall`s to an `Executor` and gets text back.

## The toolsets

| toolset | tools | opt-in? |
|---|---|---|
| `files` | `read_file`, `write_file`, `list_dir`, `glob_files` | default |
| `shell` | `run_command` | default |
| `notes` | `tell` | yes — a card must name it |

`TOOLSETS` maps a name to either a fixed list of `Tool`s or a *factory*. A
toolset that must know who is running it (`notes` needs the sender) is a
factory, built per executor; the rest are shared module-level lists.
`DEFAULT_TOOLSETS` is `["files", "shell"]`.

A `Tool` is a `ToolDef` (name, description, JSON Schema) plus a coroutine taking
`(workdir, arguments)`. Adding one is a function and a list entry.

## Failure is text, not an exception

```python
try:    return ToolResult(await tool.run(self.workdir, call.arguments))
except ToolError as exc:      return ToolResult(str(exc), error=True)
except Exception as exc:      return ToolResult(f"{type(exc).__name__}: {exc}", error=True)
```

An expected failure (`ToolError` — path escapes the workdir, no such file,
command timed out) and an unexpected one (a bad argument shape from the model)
both come back as text the model reads and can correct. Only harness bugs
outside `execute()` raise. An unknown tool name is answered the same way.

## Confinement

`files.resolve_path()` resolves every path against the workdir and refuses
anything that escapes. It calls `Path.resolve()`, so a symlink pointing outside
is caught too.

`shell.run_command` pins the command's **cwd** to the workdir — but the command
itself can still name absolute paths. That boundary needs an OS sandbox, and the
local executor does not claim to be one. This is the honest limit of the default:
path confinement prevents accidents, not a malicious model. Commands are killed
as a process tree on timeout (default 120s, max 600s) and output is capped.

## The seam

`make_executor(workdir, toolsets, tool_context)` is **the one place that decides where
tools run**. Callers hand over a setting and use what comes back, so nothing
upstream names a backend:

```
tool_context.isolation is None  →  LocalExecutor   (nothing to set up or tear down)
otherwise                       →  DockerExecutor  (import lives inside the branch)
```

The Docker import is inside the branch on purpose: a machine that never isolates
never pays to load it.

Subclasses differ only in *where* the tools run, never in what a caller does with
them — `async with`, then `definitions()` and `execute()`.

## ToolContext

`ToolContext` is one object carrying everything an agent node's tools need beyond a
workdir and a toolset list:

```python
ToolContext(isolation=…, containers=…, postbox=…)
```

`containers` and `postbox` are typed `Any` deliberately: only the `tools` package may
know what they are. The runtime carries `ctx.tool_context` and never opens it, which is
how `runtime/` stays unaware that containers or journals exist. The daemon builds
one per task, because the container pool is shared across tasks and the roster of
tasks is only known there.

## Isolation

`tools/docker.py` is the only module in poieo that knows Docker exists.
`Isolation` (in `tools/__init__.py`) is deliberately backend-neutral and free of
Docker words — `image`, `network: none|bridge`, `user` — so everything
downstream sees only that shape.

**Only `run_command` gets a container.** File tools stay the host
implementations: `resolve_path` already confines them, and routing them through
`docker exec` would add quoting, encoding and ownership bugs to code whose blast
radius is already correct. The hole is the shell, so the shell is what gets
closed.

The workdir is **bind-mounted, not copied**. Host file tools and the container's
shell must see the same bytes at the same instant, or the model writes a file it
then cannot compile.

### Kept containers

A task's container is kept alive between runs (`sleep <forever>`, then
`docker exec` per command), so what it installs on Monday is there on Tuesday.
The daemon holds a `ContainerPool` — one per distinct folder-and-settings,
shared by tasks over the same folder — and destroys them on shutdown. `poieo
run --isolate` has no next run to keep one for, so its executor makes its own
and destroys it.

`container_key()` says what makes two of them the same — folder and settings,
nothing about who asked — so two cards standing over one repo share a
toolchain instead of installing it twice. The cost of that sharing is that they
can disturb each other inside it; what they cannot disturb is anything outside
the folder, which is the boundary the feature is about.

A container is disposable derived state. `poieo reset <task>` throws it away
and the next run rebuilds it; nothing in the user's folder is touched. At
startup the daemon sweeps every container labelled `poieo.box` older than 7
days — an *age* cap rather than an idle one, since docker records when a
container was created, not when it was last used. That reclaims what a crash
left behind and what deleted tasks abandoned, at a cost of about one rebuild a
week for an hourly task.

(The label value stays `poieo.box`: changing it would orphan every container a
running daemon already made.)

### Preflight

`daemon.config.check_isolation()` verifies at load time that docker answers and
that every named image is already present — poieo never pulls for you. It is the
slowest preflight in the codebase and the only one that reaches outside the
process; what buys the cost is that a task whose image was pruned last week must
not discover it at 3am. Tasks that never asked for isolation are not probed at
all, so a machine with no docker pays nothing.

`IsolationError` is never recovered from by falling back to the host. A task that
asked to be fenced and cannot be does not run unfenced.

## Notes

The `notes` toolset gives a card one tool, `tell`, which appends a line to
another card's journal — the same file and the same shape the user writes by
hand. There is no queue, no inbox, and nothing new for the user to learn.

The sender lives in the `Postbox` the daemon builds, not in a tool argument,
precisely so a model cannot claim to be someone else. The recipients are the
other cards in the project, and the generated system prompt lists them by name —
a model cannot address a task it does not know exists.

A note is **news, not an instruction**: the recipient is a model reading text and
may ignore it. And a note **wakes nobody** — it is read on the recipient's next
scheduled run, which is why two cards writing to each other cannot spin each
other up. See [tasks.md](tasks.md).
