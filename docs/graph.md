# Graph — the logical layer

`src/poieo/graph.py`, `src/poieo/expr.py`

A graph says **what work happens and in what order**. It names roles, never
models; the [binding](binding.md) is the other half. Everything here is
pydantic models with `extra="forbid"`, so an unknown key is a load error rather
than a silently ignored line.

## The shape

```
GraphSpec
  name, version, description
  entry            the node the walk starts at
  nodes[]          NodeSpec
  state            seed for the persistent `state` mapping
  max_steps        cycle guard (default 100)
  default_role     role for model nodes that do not name one
```

`NodeSpec` is one class for both node types rather than a union, with a
`_check_shape` validator that rejects the combinations that make no sense: an
`agent` with `branches`, a `router` with a `prompt` or a `workdir`. One class
keeps the YAML flat and the error messages specific ("router node 'route' does
not call a model; drop prompt/role").

| type | reads | produces |
|---|---|---|
| `agent` | `role`, `system`, `prompt`, `output`, `retry`, `params`, and — only with hands — `tools`, `workdir`, `max_turns` | the completion of the turn that used no tool |
| `command` | `command`, `output`, and optionally `workdir`, `timeout`, `env` | `{exit_code, output}` -- the code as the number the process returned |
| `router` | `branches[].when` / `.to` / `.label`, `default` | the matched branch's label |

Three types, split by **who does the step**: the model (`agent`), the machine
exactly as written (`command`), or nobody (`router`). That line is not a
detail — it decides whether a step costs a turn, whether it gives the same
answer twice, and whether the log records a fact or a paraphrase of one.

A `command` node exists because the alternative is asking a model to read
`exit code: 0` and say so. That is a turn spent on no judgement, and a place
for a small model to be wrong about something the machine already knew — a
router branching on the model's account of a test run rather than on the test
run. The node puts `exit_code` in scope as the **number the process returned**,
and the router decides what counts as passing, because that varies and the
node should not hold an opinion about it.

**A non-zero exit is not a failed run.** A red suite is what the graph is there
to react to. The run fails only when the command could not run at all — a
timeout, a missing program — because *this did not start* and *this went red*
are different facts, and a graph that cannot tell them apart will eventually
report a suite it never ran.

`command` nodes refuse `role`, `system`, `prompt`, `params`, `retry`,
`max_turns` and `tools`: a key that does nothing reads as configured, which is
worse than one that is missing. The command runs through
`tools.make_executor()`, the same seam the model's own commands go through, so
a task that asked to be fenced is fenced here too. **No `tools:` line
means no tools**: the node calls the model once, reads the answer, and cannot
touch a file. Tools are what bring the loop, the `workdir` and the turn budget
with them, which is why there is no separate type for a call without them —
and why hands are asked for rather than defaulted.

`next: null`, or an omitted `next`, ends the run. A branch with `to: null` ends
it too — matched, and deliberately no further.

`OutputSpec` is how a node's result enters the run's scope: `as` names it at the
top level, `format: json` parses the completion, `path: a.b` digs into it, and
`into_state: k` also writes it to `state` so the next iteration can read it.

`UiSpec` (`ui: {x, y}`) is canvas coordinates. The editor writes it, the runtime
ignores it — it exists so a graph laid out in the editor keeps its layout.

## What is validated, and when

All of it at load. `load_graph()` is the only entry point, and it fully
validates before returning:

- **node ids** are alphanumeric (plus `-`/`_`), never start with a digit, and are
  unique
- **every target exists** — `next`, `default`, and each `branch.to` name a
  declared node
- **every node is reachable** from `entry` (a walk over the same edges);
  unreachable nodes are an error, not a warning, because they are always either
  a typo or dead weight
- **every template and condition parses** — `validate_template()` on `prompt`,
  `system` and `workdir`, `compile_expr()` on each `branch.when`
- **every named toolset exists** in `tools.TOOLSETS`

What is *not* checked here is anything physical: whether the roles resolve, and
whether an agent node has somewhere to work. A graph is meant to be portable
across machines, so `workdir` may legitimately be absent and supplied by the
task. `runtime.executor.preflight()` is where "nowhere to work" fails.

`graph.roles()` returns every role the graph needs — `binding.check_roles()`
consumes it, and that pairing is the whole role contract.

## Errors a user reads

`SpecError` from `load_graph()` carries `describe_invalid()`'s rendering, not
pydantic's: `'promt' is not a setting here -- did you mean 'prompt'?`. The
candidate keys are `GraphSpec`'s *and* `NodeSpec`'s, because a node's settings
are as much part of a graph file as the graph's own, and the match is made on
the last path segment so a typo nested at `nodes.0.promt` gets the same help.

## Expressions

Three surfaces use one small sandboxed language:

- prompt templates — `"Classify: {{ input.text }}"`
- router conditions — `"category.lower() == 'bug' and state.retries < 3"`
- a task's `then:` branches — `"run.change and run.steps > 2"` (see
  [daemon.md](daemon.md))

`expr.py` walks a whitelist of AST node types. Everything outside it — imports,
lambdas, comprehensions, dunder or `_private` access, walrus, f-strings — is
rejected **at parse time**, which is graph-load time, so a bad expression cannot
surface halfway through a 3am run. Attribute access is allowed only on plain
data types, which keeps `"BUG".lower()` working without opening `().__class__`
walks. A short list of builtins (`len`, `str`, `any`, `sorted`, `json_loads`, …)
is in scope; `**` refuses an exponent over 64 so `10 ** 10 ** 10` cannot hang the
daemon.

Every one of those three expressions was typed into a **YAML** file, so `true`,
`false` and `null` resolve alongside Python's `True`, `False` and `None`. They
are aliases, not replacements — the source is still parsed as Python, and the
scope is checked first, so a run carrying data named `true` keeps it. Without
them `when: "true"` failed with `unknown name 'true'`, which in a router is loud
and in a task's `then:` block is the quietest possible bug: an unreadable
condition there is logged and skipped, so the branch simply never fires.

`DotDict` is why `input.text` works on data that arrived as plain JSON: run data
is wrapped once at the boundary (`wrap()`), and `unwrap()` is its inverse for
anything that gets persisted. An attribute miss on a mapping reports what *was*
there — `no 'journal' here; this has: memory, message` — because a template
naming a key the run does not carry is the commonest authoring mistake.

`render()` substitutes every `{{ … }}`; a non-string result is JSON-encoded, so a
dict lands in the prompt as valid JSON rather than a Python repr with single
quotes.

The names in scope are assembled by `RunContext.scope()` — see
[runtime.md](runtime.md).

## Cycles

Cycles are not a defect to be detected; they are how a graph keeps going.
`examples/tasks/draft-review.graph.yaml` loops draft → review → revise until the
critic approves, counting its own attempts with `run.path.count('revise')`.
`max_steps` is the only bound, and hitting it raises `RunAborted` with the
`cycling` cause, which reads as *"the graph kept cycling; add an exit condition,
or raise max_steps"*.

## Adding a node type

Add the literal to `NodeSpec.type`, the shape rules to `_check_shape`, and the
class to `runtime.nodes.NODE_TYPES`. Nothing else knows the list.
