# Runtime

`src/poieo/runtime/`

The runtime executes one validated graph against one binding and returns one
`RunResult`. Scheduling, task-card expansion, journals, workspaces, and daemon
residency are supplied by callers and remain outside this package.

## Run context

`RunContext` holds the graph, binding, provider pool, run store, input, graph
state, iteration, cancellation signal, work directory, and opaque tool context.
During execution it accumulates node outputs, output aliases, usage, the visited
path, and an optional question.

Templates and conditions receive a read-only public scope:

```text
input              payload supplied to this run
state              graph state, including state carried from an earlier run
nodes              outputs keyed by node id
run                id, task, trigger, iteration, path, usage, elapsed time
<output aliases>   aliases declared by completed nodes
```

The runtime carries `ToolContext` but does not inspect its container, postbox,
or build cache. That keeps isolation and task-to-task notes behind the tool
interface.

## Execution

`execute()` preflights role resolution and work-directory requirements, creates
the context, emits `run_started`, and walks from `graph.entry`. Each step emits
`node_started` and `node_finished`; the node result selects the successor.
Cycles are normal, with `max_steps` as the final graph-level guard. Cancellation
is checked between nodes and between turns inside an agent node.

Node behavior is described in [graph.md](graph.md):

- an agent resolves a role, renders its prompts, calls a provider, and may loop
  over tool calls;
- a command runs through the executor and returns its numeric exit code and
  output;
- a router chooses its first matching branch;
- a confirm node records a fixed-choice question and ends the walk.

An agent conversation retains recent tool results, clears older results when
the model's reported context use or a conservative fallback limit requires it,
and compacts older turns only as a later resort. A single result that does not
fit is replaced with an instruction to fetch the data in pieces. Reaching a
model's length stop without a complete answer fails the node rather than
presenting a truncated response as success.

Tools that execute through poieo's executor -- direct endpoint calls and the
tools lent to Claude Code -- also ask the model for one short, user-facing
sentence describing what that call is meant to accomplish. The runtime carries
it in a reserved display-only field, removes it before execution, and records
it beside the bounded arguments and result. It tolerates an omitted sentence;
the board then falls back to a conservative description rather than inventing
intent. Codex owns its CLI tool loop, which does not return those calls through
the executor; its final model account remains the activity available to poieo.

## Usage and cost

Every provider response contributes its input, output, cache-read, cache-write,
and reasoning token counts. Cost reported by an endpoint, or calculated from
binding prices when the endpoint omits it, is accumulated with the token usage.
The totals include retries, agent turns, and every model-calling node. They are
available to router expressions while the run is in progress and are persisted
in the final summary. A run with no known cost keeps `cost: null`; a run mixing
known and unknown charges retains only the known subtotal and may undercount.
See [binding.md](binding.md) for pricing and provider rules.

## Results and failure

`RunResult` records the run and project ids, task, graph, status, timestamps,
steps, visited path, usage and cost, node outputs, aliases, ending state,
trigger, iteration, raw error, actionable cause, optional change, optional
question, and eventual answer. Status is one of `completed`, `failed`,
`aborted`, or `asking`.

Its summary is the append-only run-list record. It always includes the last
text produced by a visited node and includes `change` and `cause` only when
present. The full event stream retains step detail.

Preflight errors raise before a run starts because the task cannot succeed as
configured. Once execution has begun, expected `PoieoError` failures are
captured as `failed`, and step-limit or cooperative-stop failures as `aborted`.
A confirm node changes an otherwise completed walk to `asking`. An external
`asyncio.CancelledError` still propagates so process cancellation retains its
normal semantics.

The optional finalizer runs before the summary is recorded. The daemon uses it
to attach a reviewable change; no later component may silently revise an
ordinary completed summary.

## Extension seams

Node implementations register by node type and receive only `RunContext`.
Providers enter through `ProviderPool`, tools and commands through `Executor`,
events through `RunStore`, and daemon-specific completion work through the
finalizer. A new runtime feature should use one of these interfaces rather than
import daemon, Git, or web state.
