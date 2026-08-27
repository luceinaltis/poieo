# Runtime — executing one run

`src/poieo/runtime/` — `executor.py`, `context.py`, `nodes.py`

The runtime turns a validated graph plus a binding into one run. It knows
nothing about the daemon, about cards, or about where the work is happening —
those arrive as arguments.

## The walker

`execute()` is a loop, not a topological sort:

```python
current = graph.entry
while current is not None:
    result = await build_node(graph.node(current)).run(ctx)
    current = result.next_node
```

A node names its own successor and a router picks between successors at run
time, so cycles are natural rather than exceptional. Two guards sit at the top
of the loop: the `cancel` event (shutdown, checked between nodes) and
`graph.max_steps`.

**`execute()` never raises for an in-run failure.** A `PoieoError` becomes
`status="failed"` on the returned `RunResult`; a `RunAborted` becomes
`"aborted"`. Only `preflight()` — spec and binding problems — raises, because
those mean the flow is misconfigured rather than flaky. This is what lets a
daemon flow log a failure and stay up. `asyncio.CancelledError` is the one
exception that is re-raised, after emitting `run_aborted`.

`preflight()` checks the two things that make a run impossible before it costs
anything: every role the graph names resolves against the binding, and every
agent node has somewhere to work (its own `workdir`, or the flow's). Checking a
graph on its own passes `require_workdir=False`, since not naming a directory is
the point there rather than a defect.

`finalize` is the last hook before the summary is written — the daemon uses it to
commit the run's change, so `RunResult.change` is present in the summary the
store keeps. Nothing gets to amend that summary afterwards.

## The context and the scope

`RunContext` is everything a node needs and everything a run accumulates: the
graph, binding, pool and store; `input`, `state`, `iteration`; `workdir` and
`tool_context`; and the running `outputs`, `aliases`, `usage` and `path`.

`ctx.scope()` builds the names expressions see:

| name | is |
|---|---|
| `input` | the payload the trigger or CLI supplied |
| `state` | the mapping that survives across iterations |
| `nodes.<id>` | any earlier node's output |
| `<alias>` | an output's `as:` name, hoisted to the top level |
| `run` | `id`, `flow`, `trigger`, `iteration`, `path` |

Aliases use `setdefault`, so a graph cannot shadow `input` or `run` by naming an
output after them. Everything is `wrap()`ped once here so `input.text` and
`input["text"]` both work — see [graph.md](graph.md).

`ctx.tool_context` is a `ToolContext` object the runtime carries and never opens. That is how
the runtime stays unaware that containers, or journals, exist at all — see
[tools.md](tools.md).

`ctx.emit()` appends one event to the run's stream. The event types are
`run_started`, `node_started`, `node_retry`, `node_turn`, `node_tool_call`,
`node_finished`, `run_finished`, `run_failed`, `run_aborted`, and `run_change`
(written by the daemon, not here).

## The three node types

`nodes.py` has one class per `NodeSpec.type`, registered in `NODE_TYPES`. The two
model-calling types share their opening and their close:

- **`_prepare()`** — pick the role (`spec.role` or `graph.default_role`), resolve
  it against the binding, take the provider from the pool, render `prompt` and
  `system`. Returns a `_Bound`: the logical half of the node having met the
  physical half.
- **`_finish()`** — shape the output, record it under the node id and its alias,
  write `into_state` if asked, and describe the step in `meta` (role, binding,
  model, usage, stop reason).

**`LLMNode`** is those two with one call between them.

**`RouterNode`** evaluates `branches` in order, first match wins, and falls
through to `default`. It calls no model. Its output is the branch's `label` (or
the condition text), which is what `node_finished` records and what a reader sees
as the decision.

**`AgentNode`** is the loop:

```
render prompt → ask the model, offering tool definitions
  ↳ no tool calls?  the node is done, that answer is its output
  ↳ tool calls?     execute each, append the results, ask again
```

`max_turns` bounds it; hitting the bound with calls still pending is a
`NodeError` carrying the `out_of_turns` cause. The executor is opened with
`async with`, so an isolated environment is set up and torn down around the whole
loop, not per call. Each turn emits `node_turn` (with the model's text and
thinking, clipped) and each call emits `node_tool_call` (arguments, result,
error flag, duration). The final `response` read after the loop is deliberately
the one that answered without a tool call.

"Keeps working" is not this loop's job — that belongs to the graph and the
daemon. This loop is only the mechanics of one step doing its work.

## Retry, and output shaping

`call_with_retry()` retries only `ProviderError`s marked `retryable`, with
exponential backoff from `spec.retry` (`attempts`, `backoff`), emitting
`node_retry` each time. Exhausting the attempts raises `NodeError` naming the
node.

`shape_output()` applies `OutputSpec`. `format: json` tolerates a markdown fence
and, failing that, makes one salvage attempt by slicing from the first `{`/`[`
to the last `}`/`]` — a model that adds a sentence before the object is common
enough to be worth one try before failing the node.

## Failures the user reads

`errors.explain_failure()` walks the exception chain and returns a `Cause`
(`slug`, `said`, `fix`) — *"ran out of turns before finishing"* / *"raise
max_turns, or make the step smaller"*. Classification happens once, in
`execute()`, at the one place the original exception still exists; everything
downstream sees only strings.

`slug` is the stable key: the daemon counts consecutive identical failures by it,
and the web groups by it. The sentences may be reworded freely; the slug may not.
An unmatched failure returns `None` — an honest "unclassified" beats a wrong
sentence, and the raw error is always kept beside the cause.

## RunResult

What comes back, and what the store keeps a summary of: `run_id`, `flow`,
`graph`, `status`, `trigger`, timestamps, `steps`, `path`, `usage`, `outputs`,
`state`, `error`, `cause`, `iteration`, and `change` (set afterwards by the
daemon). `summary()` omits `change` and `cause` when absent rather than writing
nulls — a run that changed nothing has nothing to review, and the difference
matters to the card that reads it.

`trigger` is **what actually fired the run**, not the schedule it may not have
used: `"run now"`, or `"after chores (something changed)"` for a handoff. That is
what lets a run be traced back to the run that caused it — see
[daemon.md](daemon.md).
