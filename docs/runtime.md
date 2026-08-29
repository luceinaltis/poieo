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
those mean the task is misconfigured rather than flaky. This is what lets a
daemon task log a failure and stay up. `asyncio.CancelledError` is the one
exception that is re-raised, after emitting `run_aborted`.

There is a fourth status, and it is neither of those two. A walk that ends at a
[`confirm` node](graph.md) leaves `ctx.asked` set, and the run comes back
**`asking`**: it did not succeed and it did not fail, it is waiting on a
person. It has its own name so that a `then:` written as
`run.status == 'completed'` cannot fire while a question stands — see
[daemon.md](daemon.md), which defers that block until the answer arrives and
then reads it as `run.answer`.

`preflight()` checks the two things that make a run impossible before it costs
anything: every role the graph names resolves against the binding, and every
agent node has somewhere to work (its own `workdir`, or the task's). Checking a
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
| `run` | `id`, `task`, `trigger`, `iteration`, `path`, `usage`, `elapsed` |

`run.usage` (the four token counts) and `run.elapsed` (seconds) are what let a
router stop a run that is still going. `max_steps` bounds the *walk*, and one
agent node with tools is a single step however many turns it spends inside it,
so it bounds neither the money nor the night:

```yaml
- when: "run.usage.output_tokens > 50000 or run.elapsed > 3600"
  to: null
```

Tokens and not an amount of money: nothing in poieo knows what a model charges,
and a price table checked in here would be wrong the week after it was written.
`elapsed` is measured on a monotonic clock, so a run that crosses an NTP
correction or a daylight-saving change does not see time jump under a threshold
somebody set. It is `perf_counter` rather than `monotonic`, which on Windows
ticks every 15.6ms — coarse enough that a run would read as having taken
exactly no time at all for its first few steps.

Aliases use `setdefault`, so a graph cannot shadow `input` or `run` by naming an
output after them. Everything is `wrap()`ped once here so `input.text` and
`input["text"]` both work — see [graph.md](graph.md).

`ctx.tool_context` is a `ToolContext` object the runtime carries and never opens. That is how
the runtime stays unaware that containers, or journals, exist at all — see
[tools.md](tools.md).

`ctx.emit()` appends one event to the run's stream. The event types are
`run_started`, `node_started`, `node_retry`, `node_turn`, `node_tool_call`,
`node_context_cleared`, `node_compacted`, `node_compact_failed`,
`node_finished`, `run_finished`, `run_failed`, `run_aborted`, and
`run_change` and `run_change_failed` (both written by the daemon, not here).

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
render prompt → over the cap? clear the older tool results
             → still over the second cap? fold the older turns into a summary
             → ask the model, offering tool definitions
  ↳ cut off?        not an answer — `out_of_room`
  ↳ no tool calls?  the node is done, that answer is its output
  ↳ tool calls?     execute each, append the results, ask again
```

**A truncated turn is checked before anything else, because it is the one that
lies.** A model that ran out of output budget mid-sentence comes back with no
tool calls — the same shape as one that finished — so half a sentence became
the node's output and the run reported success. Endpoints say which it was:
OpenAI-shaped ones `finish_reason: length`, Anthropic `max_tokens`, and
`LLMResponse.stop_reason` has carried it all along. Hitting it is a `NodeError`
carrying `out_of_room`, whose fix is the budget rather than the turn count —
and a model that reasons spends that budget on thinking as well as answering,
which is how a one-word verdict comes back empty.

**The conversation is bounded, because nothing else bounds it.** Every tool
result is appended and resent on every turn after it, so a step that reads
twenty files pays for all twenty on every remaining turn -- one run measured
here spent 160,360 input tokens to produce 6,578 of output before it was cut
off mid-turn. Past half of what the model can hold the older tool results are replaced by
a short note, and `node_context_cleared` says how much that freed.
**Only the result goes, never the request:** the assistant turn that asked for
the file stays, so the model still knows it has read it, and the tools are
offered again every turn, so it can read it again. The worst case is one
repeated call rather than a fact lost for good, which is why this is preferred
here to summarizing the same history. `_KEEP_RESULTS` most recent results are
always kept whole, and clearing fires only past the cap rather than every turn
-- an endpoint that caches prompt prefixes would otherwise find a different
prefix every turn and charge for the whole conversation to save part of it.

**And a second cap above it, for what clearing cannot reach.** Clearing empties
tool results, but the turns themselves keep accumulating -- the model's own
reasoning, and tool call arguments, which for a `write_file` are a whole file.
Past `_COMPACT_CAP` the turns older than the last `_KEEP_TURNS` are folded into
a summary the model writes, which is appended to the first message rather than
added beside it: that message is the task, the task is never folded away, and
keeping the two together avoids asking either API to accept two user turns in a
row. **The cut always lands on a turn boundary** -- where the model speaks --
because a tool result whose call is gone is rejected outright by both APIs.

Two things keep this from running away. It only fires when the fold would
reclaim at least `_FOLD_AT_LEAST`, without which it would fire on every turn
after the first: a fold leaves exactly `_KEEP_TURNS` behind it, so the next turn
is over the line again. And a summary that cannot be written is not worth losing
the step over -- the history is left whole, `node_compact_failed` records it,
and the run carries on to fail honestly on room if it is going to.

Clearing before folding, and not the other way around, because clearing costs
nothing and is one repeated tool call away from being undone, while a fold
costs a model call and loses whatever the summary left out.

**Both caps are the model's.** A model's
window is a fact about the model, so it lives on the binding's `context:` --
and where nobody has written it down, the endpoint is asked once and its
answer remembered. Both thresholds read it: clearing at half of it, folding at nine tenths,
the same shape as Anthropic's own 100k/180k defaults for a 200k window. What is
compared against it is `usage.input_tokens` from the previous response, which
is a measurement the endpoint already sends rather than an estimate from
characters. It lags by one turn, which is what a threshold on a measurement
costs and what the server-side version costs too.

Where the binding says nothing, the character caps above are what this loop had
before anyone could say. They are wrong for every model these examples bind --
`_CONTEXT_CAP` is 2.3% of what `z-ai/glm-5.3-flash` holds and 11.4% of a local
qwen3.5 -- which is why the binding is the better answer and the constant is
only the fallback.

`max_turns` bounds the turns; hitting that bound with calls still pending is a
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

What comes back, and what the store keeps a summary of: `run_id`, `task`,
`graph`, `status`, `trigger`, timestamps, `steps`, `path`, `usage`, `outputs`,
`state`, `error`, `cause`, `iteration`, and `change` (set afterwards by the
daemon). `summary()` omits `change` and `cause` when absent rather than writing
nulls — a run that changed nothing has nothing to review, and the difference
matters to the card that reads it.

`trigger` is **what actually fired the run**, not the schedule it may not have
used: `"run now"`, or `"after chores (something changed)"` for a handoff. That is
what lets a run be traced back to the run that caused it — see
[daemon.md](daemon.md).
