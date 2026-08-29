# Tools — the hands

`src/poieo/tools/` — `__init__.py`, `files.py`, `shell.py`, `notes.py`, `docker.py`

An agent node hands the model tool definitions and executes what it asks for.
A node never touches the filesystem or a subprocess directly: it hands
`ToolCall`s to an `Executor` and gets text back.

## The toolsets

| toolset | tools | opt-in? |
|---|---|---|
| `files` | `read_file`, `write_file`, `edit_file`, `append_file`, `list_dir`, `glob_files`, `search_files` | default |
| `shell` | `run_command` | default |
| `notes` | `tell` | yes — a card must name it |

`TOOLSETS` maps a name to either a fixed list of `Tool`s or a *factory*. A
toolset that must know who is running it (`notes` needs the sender) is a
factory, built per executor; the rest are shared module-level lists.
`DEFAULT_TOOLSETS` is `["files", "shell"]`.

A `Tool` is a `ToolDef` (name, description, JSON Schema) plus a coroutine taking
`(workdir, arguments)`. Adding one is a function and a list entry.

## Reading part of a file

`read_file` numbers its lines, and takes `offset` and `limit` to read a window
rather than the whole thing. The numbers are what make a range askable --
Anthropic's text editor calls them "essential" for exactly that -- and
`search_files` answers with line numbers that go straight into one.

They cost something: a model may copy a number into an `edit_file` call. That
is why matching takes them back off rather than failing on them. The reference
implementations instead tell the model to strip them, which works until the
model forgets.

**There is no default window.** SWE-agent measured whole-file reads at 5.3
points below a window, and a window too *narrow* at 3.7 below a wider one --
too little context is its own failure. How much to read is the model's to
choose; only the ceiling is ours.

### `_READ_CAP` is a guard, not context management

It is 200,000 characters and stays there, and that is a decision rather than an
oversight. The largest file in this repository is 54,921 characters, so the cap
has never fired on it -- and the conversation that ran to 271,064 characters got
there on **four mid-sized files**, none of which any per-file cap would have
stopped.

Bounding the conversation is the agent loop's job, and since the caps became the
model's (`docs/runtime.md`) it does it against a number that means something.
This one is here for the pathological single file -- a minified bundle, a log --
and the tools stay ignorant of which model is reading them, which is worth more
than making one number derive from another.

What it did owe was a way out: a truncated read now cuts on a line and hands
back the `offset` to carry on from. Before windows existed `... [truncated]` was
all there was to say; it is not any more.

## Changing part of a file

`edit_file` replaces `old` with `new`, and refuses unless `old` appears exactly
once. Ambiguity is an error rather than a guess: quietly changing the first of
three is the failure nobody notices until the tests do. `append_file` adds to
the end, which in a measured run was **four of the five file surgeries** the
model performed -- as `cat >> file << 'EOF'`, which the Windows shell rejected
outright, and as a write-a-temp-file-then-append-it-then-delete-it dance.

**Matching is forgiving in three steps; the safeguard is not.** Exact first;
then with the line numbers a file viewer prints taken off, because the
reference implementations number their output and then ask the model to
remember to strip them, and a model that needs the reminder is one that will
miss it; then ignoring trailing whitespace and line endings, which is where the
reported edit failure rates on models never trained on this shape mostly live.
**Leading whitespace is never forgiven** -- in Python indentation is meaning,
and a different depth is a different block. Uniqueness is still required no
matter which reading matched.

**A Python file that would stop parsing is not written.** `compile()` from the
standard library, checked before the write, and the file is left as it was.
SWE-agent's ablation puts a linting edit command three points above one without
it: a broken file is worse than a refused edit, because the model finds out one
test run later and spends its next turns debugging its own typo.

## Searching is a tool, not a shell command

`search_files` takes a regular expression and answers `path:line: text`. It
exists for the same reason `run_command`'s `env` does: in a measured run,
**twenty-three of seventy shell commands were `grep`**, and the POSIX spelling
of one of them died on a Windows shell. A search is not about the shell, so the
shell's dialect should not decide whether it works.

**It is capped twice, in matches and in the length of any one line, and this
matters more than it looks.** SWE-agent's own ablation measured an
unsummarized, iterative search scoring *six points below having no search at
all*: an answer that fills the context is worse than no answer. It also stays
out of dot-directories -- a run's folder is a git copy, so `.git` is packs and
objects, which are noise at best and binary at worst.

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

## Which shell, and saying so

`run_command` runs through **a POSIX shell where one exists**, including on
Windows, where `create_subprocess_shell` would otherwise use `COMSPEC` --
`cmd.exe`. A model writes POSIX; so does this repository's own AGENTS.md.

The measured run that prompted this is the argument. Unix binaries were on
PATH, so `grep` went 21/23 and `sed` 3/3 -- and then a heredoc came back
`<<은(는) 예상되지 않았습니다`, because the *binaries* were POSIX and the
*syntax* was cmd.exe. Nothing had told the model which it was talking to, so
the tool's description now opens by naming it, built from what was found rather
than hardcoded.

**`C:\Windows\System32\bash.exe` is refused.** It is the WSL launcher: it
starts a Linux distribution with its own filesystem, so the `cwd` points
somewhere else entirely and the command *succeeds* there. Running quietly in
the wrong directory is worse than failing in the right one.

Where no POSIX shell is found the old behaviour stands, and the description
says so plainly along with what will not work.

**The same choice decides how a path is spelled**, which is why `quote_path`
lives here rather than where the path is made. On Windows with a POSIX shell a
backslash is read as an escape and eaten, and a command that is one
double-quoted word with no space in it loses its quotes before bash parses it —
so a built binary at `C:\…\prog` fails as an unterminated string, and unquoted
it fails as `C:Users82109…`. Forward slashes and POSIX quoting survive both,
with a space or without. Without a POSIX shell the reverse holds: `cmd` wants
backslashes and does not read single quotes as quoting at all.

## Confinement

`files.resolve_path()` resolves every path against the workdir and refuses
anything that escapes. It calls `Path.resolve()`, so a symlink pointing outside
is caught too.

`shell.run_command` pins the command's **cwd** to the workdir — but the command
itself can still name absolute paths. That boundary needs an OS sandbox, and the
local executor does not claim to be one. This is the honest limit of the default:
path confinement prevents accidents, not a malicious model. Commands are killed
as a process tree on timeout (default 120s, max 600s) and output is capped.

It also takes an **`env`** object, laid over the process environment rather than
replacing it. That exists because shells disagree about how to set a variable
for one command — `VAR=1 command` is POSIX and a Windows shell reads `VAR=1` as
the program to run, failing with the *same exit code* a program that ran and
failed would. A step told to run one exact command then cannot tell "this did
not start" from "this went red", which is how a gate comes to report a suite it
never ran. Passing the variable as data takes the shell's dialect out of it.

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

### Entering the seam directly

`Executor.run_command(command, timeout, env)` is the same seam without a model
in front of it, and it answers with a `CommandResult` — `exit_code` as the
**number the process returned**, `output` as the text.

That distinction is the point. `run_command` the *tool* hands a model
`exit code: 0\n…`, because a model reads text; anything branching on "did this
pass" wants the number, and a sentence about a number is a thing that can be
misread. One implementation, two shapes: the tool is `result.as_text()` over
this.

A caller that shelled out for itself instead would work on a host and quietly
escape the container on a task that asked to be fenced. Half a fence is worse
than none — nobody knows which half.

### `run_script` — and why languages live here

`Executor.run_script(language, script, timeout, env)` runs code in a named
language. An interpreted one (`LANGUAGES` — `python -`, `node -`, `sh -`) reads
it from stdin and leaves nothing behind. A compiled one (`COMPILED` — `c`, `go`,
`rust`) cannot, because a compiler wants a path, so the source is written, built
and run under `build_paths()`, keyed by `cache_key()` — the sha256 of the
language and the code, as `blob.py` names its keepsakes. The build is skipped
when that hash's binary is already there.

The table lives on the executor rather than on the node because **where a thing
is built is where it has to run**: a binary made on this host will not run in a
Linux container, and only the executor knows which of those it is. So each
subclass answers `build_paths()`, `_is_built()`, `_put()` and `quote()` for its
own filesystem — the local one with `Path` joins under the project's cache (or
the OS temp folder outside a project), the Docker one with posix paths under
`/tmp/poieo-build/` *inside* the container, written over `docker exec -i`.
`quote()` is on that list for the same reason the rest are: only the executor
knows which shell will read what it hands over (see above).

`_put` writes tmp-then-`os.replace`, for the same reason `blob.py` does: a torn
write must not leave a wrong body under a right name, which here would mean
building yesterday's code and calling it today's.

See [graph.md](graph.md) for the user-facing half — the `env:` rule that bounds
the cache, and why there is no expiry to write.

## ToolContext

`ToolContext` is one object carrying everything an agent node's tools need beyond a
workdir and a toolset list:

```python
ToolContext(isolation=…, containers=…, postbox=…, build_cache=…)
```

`containers` and `postbox` are typed `Any` deliberately: only the `tools` package may
know what they are. `build_cache` is the project's `memory/cache/builds/`, and
it is *passed in* rather than worked out from the workdir — `layout_for()`
answers with the workdir itself when it holds no `poieo.yaml`, so a cache
derived there would land inside the user's repository, which is committed whole
as the night's change. The runtime carries `ctx.tool_context` and never opens it, which is
how `runtime/` stays unaware that containers or journals exist. The daemon builds
one per task, because the container keeper is shared between them all and the
roster is only known there.

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
