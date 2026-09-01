# Tools and isolation

`src/poieo/tools/`

Agent nodes receive named toolsets. Every tool call goes through an `Executor`,
which supplies a working directory, converts expected failures to text the model
can act on, and decides whether commands run on the host or in an isolated
environment.

## Toolsets

| toolset | model-visible tools | default for a prompt card |
|---|---|---|
| `files` | `read_file`, `write_file`, `edit_file`, `append_file`, `list_dir`, `glob_files`, `search_files` | yes |
| `shell` | `run_command` | yes |
| `notes` | `tell` | no |

Explicit graph agent nodes receive no tools unless `tools` names them. A prompt
card with no `tools` field receives `files` and `shell`; an empty list means no
tools. `TOOLSETS` is the extension registry. A fixed toolset is a list of tool
definitions and coroutines; a context-dependent toolset, such as notes, is a
factory built for each executor.

## File boundary

Every file path is resolved against the work directory, including symlinks, and
is refused if the result escapes it. Glob patterns cannot climb through `..`.
Reads are line-numbered and may request an offset and limit. Reads, globs, and
regular-expression searches have output limits; search skips dot-directories
and unreadable or binary files.

`edit_file` replaces one uniquely matching block. It tolerates copied line
numbers, line endings, and trailing whitespace but never changes indentation
semantics. A Python edit that would not parse is refused before writing.
`append_file` requires an existing file, while `write_file` may create one and
its parents.

These are accident boundaries, not claims about a hostile process. The local
shell's current directory is pinned, but a command can name an absolute host
path. Use task isolation when commands must be prevented from reaching outside
the work directory.

## Commands and scripts

`run_command` reports the numeric exit code and combined output. Environment
values are passed as data and layered over the process environment, avoiding
shell-specific assignment syntax. Time and output are bounded, and timeout
kills the process tree.

On Windows poieo uses a POSIX shell when a genuine local one is available and
otherwise tells the model it is using `cmd.exe`. The WSL launcher is refused
because its filesystem would not represent the supplied Windows working
directory. Path quoting follows the shell actually selected.

Graph command nodes enter `Executor.run_command` directly and retain the
numeric exit code for routing. `run_script` sends interpreted source on stdin.
Compiled languages use a content-addressed build cache owned by the executor:
host builds live in the project cache or system temporary directory, while
isolated builds live inside the container. Variable input belongs in `env` so
unchanged compiled source can reuse its binary.

## Failure contract

An unknown tool, a path refusal, bad arguments, timeout, or other expected tool
failure returns `ToolResult(error=True)` with explanatory text. The model may
correct the call without losing the run. A command node has no model in that
loop, so an executor error fails the node; a completed command with a nonzero
exit code remains ordinary output.

Only failures outside the executor's call boundary may raise as harness bugs.
Never introduce a tool that performs its own subprocess or filesystem work and
bypasses these rules.

## Isolation

A task may request:

```yaml
isolation:
  image: python:3.12-slim
  network: none       # or bridge
  user: 1000:1000     # optional
```

The schema is backend-neutral. The current isolated executor uses Docker and
changes where commands run; file tools stay on the host behind their resolved
path fence. The task work directory is bind-mounted at `/work`, so both sides
see the same bytes. The image must already be present: startup checks that
Docker answers and every enabled task's image exists, and never pulls an image
implicitly. Failure to provide requested isolation is fatal to task preflight;
poieo never falls back to the host.

`network: none` is the default. `bridge` grants the container Docker's normal
network access. The work directory remains deliberately exposed, containers
share the host kernel, and provider requests and model prompts are not moved
inside the container. Isolation narrows command reach; it is not a virtual
machine or a credential vault.

The daemon keeps one container for each distinct work directory and isolation
setting, so tasks sharing both may also share installed tools and may disturb
each other inside that environment. Containers are derived state: shutdown or
reset can remove them, and the next run recreates them. A one-shot isolated run
creates and removes its own container. Startup cleanup reclaims old labelled
containers left by crashes.

Subscription providers may impose stricter execution rules. In particular,
Codex uses its own sandbox and refuses poieo tool or isolation settings it
cannot enforce. See [binding.md](binding.md).

## Notes and extension

The `notes` toolset receives a `Postbox` with a fixed sender and the other task
ids in the same project. `tell` appends a stamped one-line note to a recipient's
journal. It cannot address itself, forge a sender, reach outside the roster, or
wake the recipient; the note is read on that task's next run.

Add a tool through `TOOLSETS`, add an execution backend through the `Executor`
contract, and pass daemon-owned resources through `ToolContext`. Callers should
never inspect container or postbox implementations.
