# Agent Node Design

**Date:** 2026-08-21
**Status:** Approved for planning

## Goal

Give a graph node hands. Today an `llm` node sends one prompt and stores one
completion — the model can *describe* an edit but cannot make one. This design
adds an `agent` node type: the model receives tool declarations (file access,
shell commands), poieo executes the calls it makes inside a confined working
directory, and the loop continues until the model answers without requesting a
tool.

The outer "keep working forever" behaviour is **not** part of this design — it
already exists (graph cycles, the daemon's `loop`/`interval` triggers,
`carry_state`). An agent node is one *step* of a user-designed flow that the
daemon keeps re-running. The tool loop inside a node is bounded mechanics, not
the resident loop.

Primary target is local models (Ollama tool-capable models such as llama3.1+,
qwen), with the Claude API equally supported through the same neutral protocol.

## Out of scope

- The web control plane / roadmap board (next sub-project; this design's
  `node_tool_call` events are recorded so that UI can replay them later).
- A `command` provider that shells out to external agent CLIs.
- The `docker` executor backend. This design ships only the `local` executor
  (path confinement), but tool execution is funnelled through an executor
  interface so a container-backed executor can slot in later without
  reshaping the node (see Tools).
- OS-level sandboxing in the default path. The `local` executor prevents
  accidents, not a malicious model (see Security boundary).

## Architecture

New pieces, minimal touch on existing files:

```
src/poieo/
  tools/                NEW  tool definitions + executor
    __init__.py              registry: TOOLSETS = {"files": ..., "shell": ...}
    files.py                 read_file / write_file / list_dir / glob_files
    shell.py                 run_command
  providers/base.py     EXT  ToolDef, ToolCall; tools on request, tool_calls on response
  providers/*.py        EXT  each backend translates the neutral types to its wire format
  runtime/nodes.py      EXT  AgentNode, registered as NODE_TYPES["agent"]
  graph.py              EXT  NodeSpec accepts type: agent + workdir/tools/max_turns
```

### One agent-node step

1. Render `prompt` (and `system`) against the normal `{{ }}` scope.
2. Call the bound model with the node's tool declarations.
3. If the response contains tool calls: execute each inside `workdir`, append
   the results to the conversation, go to 2.
4. A response with **no tool calls ends the loop**; its text is the node's
   output, shaped by the existing `output:` spec (`as`, `format: json`,
   `path`, `into_state`).
5. Emit a `node_tool_call` event per executed call; proceed to `next`.

## Graph schema

```yaml
- id: improve
  type: agent
  role: worker                # resolved via the binding, same as llm
  workdir: ~/projects/myapp   # REQUIRED; {{ }} templates allowed
  tools: [files, shell]       # optional; default is both toolsets
  prompt: |
    Pick one untested module and add tests for it.
  max_turns: 30               # optional; default 20, cap 200
  output: {as: report}
  retry: {attempts: 2}        # applies to provider failures, as on llm nodes
```

Validation at load time (SpecError, not 3am failures):

- `agent` requires `prompt` and `workdir`; `branches` are rejected.
- Unknown toolset names in `tools` are rejected against the registry.
- `workdir` existence is checked at *run* time (it may be templated), with a
  clear NodeError if missing.

## Provider protocol

Neutral types in `providers/base.py`:

```python
@dataclass(slots=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict          # JSON Schema

@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict
```

- `LLMRequest.tools: list[ToolDef]` (empty = plain completion, today's path).
- `LLMResponse.tool_calls: list[ToolCall]` (empty = the model is done).
- Neutral message history: user turn; assistant turn carrying `text` and/or
  `tool_calls`; tool-result turn carrying `tool_call_id` + `content`.

Per-backend translation:

| provider | tool declaration | calls in response | results sent back as |
|---|---|---|---|
| anthropic | `tools=[...]` | `tool_use` content blocks | `tool_result` blocks in a user turn |
| ollama | `tools=[...]` on /api/chat | `message.tool_calls` | `role: tool` messages |
| openai_compatible | `tools=[...]` | `choices[].message.tool_calls` | `role: tool` messages |
| mock | script entries may be `{tool_calls: [{name, arguments}]}` | scripted | recorded on `.calls` for assertions |

A backend/model that cannot do tool calling fails with a clear
`ProviderError` naming the model.

## Tools

All execution funnels through an **executor** — one object that owns "run
this tool call inside this workdir". The node never touches the filesystem or
a subprocess directly; it hands `ToolCall`s to the executor and gets result
text back. This design implements a single executor, `local` (direct
execution with path confinement, below). A future `docker` executor runs the
same calls inside a container with the workdir mounted, selected per node
(`sandbox: docker`, an `image:` field); nothing else about the node changes.
The schema reserves no fields for it yet — they arrive with that backend.

**files** toolset:

| tool | signature | notes |
|---|---|---|
| `read_file` | `(path, offset?, limit?)` | >200KB is truncated with an explicit marker |
| `write_file` | `(path, content)` | creates parent directories |
| `list_dir` | `(path?)` | name/type/size listing |
| `glob_files` | `(pattern)` | recursive `**/*.py` style |

**shell** toolset:

| tool | signature | notes |
|---|---|---|
| `run_command` | `(command, timeout?)` | cwd pinned to workdir; default 120s, max 600s; stdout+stderr combined, truncated to 20KB; exit code always reported |

Confinement rules:

- Every path argument is resolved against `workdir`; after `resolve()` (which
  follows symlinks) the result must stay under `workdir`, blocking both `../`
  and symlink escapes.
- Tool *errors* (missing file, non-zero exit, timeout, blocked path) are
  returned to the model as error text in the tool result — never a node
  failure — so the model can correct itself and retry. This is what makes the
  loop practical.

### Security boundary

Path confinement prevents *accidents*. A shell command can itself touch
absolute paths; the `local` executor cannot prevent that and this design does
not claim to. Run flows against a workdir you would let a junior contributor
loose in. Real isolation is the future `docker` executor's job — and even
then the mounted workdir remains exposed by definition (editing it is the
work); reviewability and rollback of those files belong to per-run git
checkpointing, a separate roadmap item. Documented in the README when this
ships.

## Failure handling

- `max_turns` exhausted → `NodeError`; the run records `failed`, the daemon
  applies the existing `on_error` policy, and the next trigger starts a fresh
  run — the resident behaviour survives individual failures.
- Cancellation (`SIGINT`/daemon stop) is checked each loop turn: finish the
  in-flight tool call, then abort the run cleanly.
- `Usage` is merged across every turn of the loop, so run-log cost accounting
  stays accurate for agent nodes.
- `node_tool_call` event fields: `{turn, name, arguments (truncated),
  result (truncated), duration_ms}` — enough for `poieo runs show` and the
  future web UI to replay what the model actually did.

## Testing (TDD)

- **tools**: path-escape attempts (`../`, absolute, symlink), truncation,
  timeout, error-text-instead-of-raise behaviour.
- **AgentNode loop**: mock provider scripted with tool calls — full
  call → execute → feed back → finish cycle; max_turns exhaustion;
  cancellation mid-loop.
- **provider translation**: request-building functions map neutral types to
  each wire format correctly, no network needed.
- **schema**: agent validation rules (workdir required, unknown toolset
  rejected, branches rejected).
- **end to end**: `poieo run` with a mock binding against a temp directory.
