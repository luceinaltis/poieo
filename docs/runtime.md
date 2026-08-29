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
`node_context_cleared`, `node_retried_smaller`, `node_input_dropped`,
`node_compacted`, `node_compact_failed`,
`node_finished`, `run_finished`, `run_failed`, `run_aborted`, and
`run_change` and `run_change_failed` (both written by the daemon, not here).

## The four node types

`nodes.py` has one class per `NodeSpec.type`, registered in `NODE_TYPES` —
`agent`, `command`, `router`, `confirm`. Only the first of them calls a model,
and two helpers hold what that takes:

- **`_prepare()`** — pick the role (`spec.role` or `graph.default_role`), resolve
  it against the binding, take the provider from the pool, render `prompt` and
  `system`. Returns a `_Bound`: the logical half of the node having met the
  physical half.
- **`_finish()`** — shape the output, record it under the node id and its alias,
  write `into_state` if asked, and describe the step in `meta` (role, binding,
  model, usage, stop reason).

**`CommandNode`** runs one command — or one `script`, handed to its language's
interpreter — through `make_executor()`, the same seam the model's own commands
go through. Its output is `{exit_code, output}`, and **a non-zero exit is not a
failed run**: the node fails only when the command could not run at all, because
*this did not start* and *this went red* are different facts. See
[graph.md](graph.md) for what `script:` costs a compiled language.

**`RouterNode`** evaluates `branches` in order, first match wins, and falls
through to `default`. It calls no model. Its output is the branch's `label` (or
the condition text), which is what `node_finished` records and what a reader sees
as the decision.

**`ConfirmNode`** renders its question, hangs it on `ctx.asked`, and returns with
no successor — which is what turns the finished walk into the `asking` status
above. It calls no model and runs nothing. What happens after the answer is the
card's `then:`, one level up, reading `run.answer`; see [graph.md](graph.md) for
why the run ends here rather than suspending.

**`AgentNode`** is the loop:

```
render prompt → over the cap? clear the older tool results
             → still over the second cap? fold the older turns into a summary
             → ask the model, offering tool definitions
  ↳ refused?        clear and ask once more, if there was anything to clear
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

Three things keep this from running away. It only fires when the fold would
reclaim at least `_FOLD_AT_LEAST`, without which it would fire on every turn
after the first: a fold leaves exactly `_KEEP_TURNS` behind it, so the next turn
is over the line again. A summary that cannot be written is not worth losing
the step over -- the history is left whole, `node_compact_failed` records it,
and the run carries on to fail honestly on room if it is going to.

**And a fold that would not shrink the conversation is not taken.** The model
is asked to be brief rather than made to be, so whether it was is checked
rather than assumed. Watched in another harness: a compression pass took a
conversation from 64,186 tokens to 71,173 -- fourteen messages in, fourteen
out, seven thousand tokens larger -- and reported it as done. Rebuilding is not
shrinking. The same `node_compact_failed` carries it, because the outcome is
the same: nothing was folded, the history is whole, and the next turn can fail
honestly on room. What differs is the sentence, and that is what a reader
needs.

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

**A refusal is a measurement nobody could have taken.** An endpoint that
rejects a request for its size knows something the loop does not: the caps
above fire on the *previous* turn's token count, so a turn that grows sharply
-- one large file, one long command -- goes out over the line before anything
here can know it. When that happens the request is cleared and sent once more.

The error text is never read. Endpoints spell "too long" differently and a
regular expression over English breaks on the next API version, so this is
bounded by what it can do rather than by what it recognises: **once per node,
and only when clearing found something to clear.** A refusal with nothing older
to drop was not about size, or was about a size nothing here can help, and
sending it again would buy the same answer twice. `node_retried_smaller` says
when it happened and what it freed.

**Not every endpoint refuses. Some just keep less.** Ollama past `num_ctx`
truncates the prompt and answers anyway, so the model replies from a
conversation with its beginning missing and nothing says a word. Measured
against a real one at 4,096: sending 45,000 characters after 18,000 made the
reported count **fall from 4,010 to 2,050**.

The invariant that catches it needs no estimate. **A conversation only grows,
so the count the endpoint reports for it must grow too.** When it does not, and
the loop did not itself shrink anything that turn, the endpoint kept less than
it was sent. Both counts have to be real numbers: a backend that reports zero
has not told us anything, and no measurement is a different fact from a bad
one.

What follows is the same ladder as everywhere else -- clear the oldest results,
then, only if nothing old enough is left, replace the newest one. That last
step is the case clearing cannot reach: a single file larger than the window
survives every clearing and every retry. It is only safe *after* the endpoint
has shown it did not fit; doing it beforehand would make the tool call
pointless and have the model read the same file forever. And it is replaced
with what to do rather than only that something is gone -- `read_file` has
taken `offset` and `limit` since the windows arrived, and a step measured here
used them zero times out of thirty-six.

With nothing left to drop the node fails, carrying `window_too_small`. Without
that, a truncating endpoint would be answered forever with garbage.

`max_turns` bounds the turns; hitting that bound with calls still pending is a
`NodeError` carrying the `out_of_turns` cause, **and the message names what
the turns were spent on.** The advice on that failure is "raise it, or make the
step smaller" -- opposite actions, and for a long time nothing said which. A
step measured here spent forty turns making ten edits and running the suite
four times: it was working and wanted more room. Another spent forty reading
the same four files: more room would have bought more of that. The tool counts
are the difference, and getting them used to mean writing a script against the
event log after the fact.

**`deadline` is the bound that matches the harm.** Seconds, like the `timeout`
beside it, and `None` for a node that does not ask. What an unbounded step
actually costs is not money -- forty turns measured here came to two and a half
cents -- it is that the step outlives its own schedule and blocks whatever was
queued behind it. "This fires hourly, so it must not take an hour" is a
sentence somebody can mean; "forty turns" is not.

Checked at the top of a turn rather than raced against the model call. A
request already sent is paid for whether or not the answer is kept, so
cancelling one mid-flight would waste the tokens the deadline was set to save.

**Turns are a poor unit and the counts are there because of it.** In one
measured run a turn cost between 15 and 1,629 output tokens, and took between
five seconds and seven minutes. Forty of them is not a budget anybody can
reason about; forty of them spent on `edit_file` and `run_command` is. The executor is opened with
`async with`, so an isolated environment is set up and torn down around the whole
loop, not per call. Each turn emits `node_turn` (with the model's text and
thinking, clipped, and what that turn cost in tokens -- a run's own record
carries one total for the whole of itself, which cannot say which turn a step
slowed down on, nor whether a model writes more as the conversation it reads
grows) and each call emits `node_tool_call` (arguments, result,
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
`aliases`, `state`, `error`, `cause`, `iteration`, and `change` (set afterwards
by the daemon).

`aliases` is those same outputs under the names their nodes gave them, kept
beside `outputs` rather than merged into it — that mapping is keyed by node id,
an alias may be anything, and one dictionary would let a graph bury one node's
output under another's alias. It exists so the card's `then:` can read a node's
result by the name the graph already calls it; see [daemon.md](daemon.md). `summary()` omits `change` and `cause` when absent rather than writing
nulls — a run that changed nothing has nothing to review, and the difference
matters to the card that reads it.

`trigger` is **what actually fired the run**, not the schedule it may not have
used: `"run now"`, or `"after chores (something changed)"` for a handoff. That is
what lets a run be traced back to the run that caused it — see
[daemon.md](daemon.md).
