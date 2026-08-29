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

`NodeSpec` is one class for every node type rather than a union, with a
`_check_shape` validator that rejects the combinations that make no sense: an
`agent` with `branches`, a `router` with a `prompt` or a `workdir`. One class
keeps the YAML flat and the error messages specific ("router node 'route' does
not call a model; drop prompt/role").

| type | reads | produces |
|---|---|---|
| `agent` | `role`, `system`, `prompt`, `output`, `retry`, `params`, and — only with hands — `tools`, `workdir`, `max_turns` | the completion of the turn that used no tool |
| `command` | `command` **or** `script` + `language`; `output`, and optionally `workdir`, `timeout`, `env` | `{exit_code, output}` — the code as the number the process returned |
| `router` | `branches[].when` / `.to` / `.label`, `default` | the matched branch's label |
| `confirm` | `prompt`, `choices` | the question it asked — and the run ends |

Four types, split by **who does the step**: the model (`agent`), the machine
exactly as written (`command`), nobody (`router`), or **you** (`confirm`). That
line is not a detail — it decides whether a step costs a turn, whether it gives
the same answer twice, and whether the log records a fact or a paraphrase of
one.

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
a task that asked to be fenced is fenced here too.

### A command is one command

A `command:` with a second line is refused at load. Two lines are one shell
string, and Windows `cmd` drops everything after the newline while still
reporting exit 0 — a step that did half its work and called it success. Chain
with `&&`, give each line its own node, or use a script.

### `script:` — the node carries its code

```yaml
- id: gate
  type: command
  language: python
  script: |
    import json, sys
    report = json.load(open("coverage.json"))
    sys.exit(0 if report["pct"] >= 90 else 1)
```

The code goes to the interpreter's **stdin** (`python -`, `node -`, `sh -`),
never through a shell. That is what stops a quote, a colon or a newline from
meaning something on the way past — `command: python -c "print(json.dumps({'k':
1}))"` does not even parse as YAML, and the quoted spelling that does needs
`''k''`.

Stdin rather than a temp file, which is what GitHub Actions writes: a file
would have to live in the workdir for a container to see it, and
[workspace.md](workspace.md) commits the workdir whole as the night's change —
so a scratch file would arrive in somebody's diff. (Their reason for a file is
`cmd` and `powershell` needing extensions; poieo calls interpreters, not
shells, and every one of those reads stdin.)

`LANGUAGES` in `tools/__init__.py` is the table, and adding one is a line. An
interpreter that is not installed fails with its own message, which is the
honest report; `sh` is absent on a bare Windows box, and that is a run-time
fact rather than something to pretend about at load.

`command:` and `script:` are exclusive, and `language:` is required with a
script — nothing can be read off the code itself, and guessing wrong runs the
wrong interpreter over somebody's program. An interpreted script is templated
and checked at parse time, exactly as a command and a prompt are; a compiled one
is not, for the reason below.

`env:` is templated too, and its values are checked at load like everything
else. That matters more than it looks: it is the one channel by which a run
reaches a *compiled* script, which is not rendered.

### Compiled languages, and why the cache is not extra

`c`, `go` and `rust` are in the table too, and they cannot use stdin: a
compiler wants a **path**. Once there has to be a file somewhere, naming its
folder by the hash of the code *is* the cache — skipping the build is then one
`if the binary is already there`. Building once and running many times is not a
feature added on top; it is what content-addressing gives for free.

Two constraints decide where that folder is, and both come from
[workspace.md](workspace.md): the workdir is committed whole as the night's
change, so nothing scratch may go there — and `layout_for()` answers with the
workdir *itself* when it holds no `poieo.yaml`, so a cache worked out from the
workdir would land inside the user's repository. The project's cache path is
passed in on `ToolContext` instead.

| | where | how long |
|---|---|---|
| local | the project's `memory/cache/builds/` | the folder's own "delete freely" contract |
| isolated | `/tmp/poieo-build/` **inside the container** | the container's, like everything else it installed |

Inside the container rather than a second mount, and that is not only
simplicity: a binary built there is for the image's platform, so a cache shared
with the host would eventually hand a Windows executable to a Linux container.

**A compiled script is not a template.** Rendering one would change the hash
every run, so the cache would never hit and would grow without bound — and it
would also be wrong about the code: `{{` belongs to the *language* here.
`[][]int{{1,2},{3,4}}` is ordinary Go and `int m[1][1] = {{0}};` is ordinary C,
and a rule that refused them would be refusing the language. So the text goes
to the compiler exactly as written, and only one thing is caught at load — a
placeholder reaching for the run's own data (`input`, `state`, `nodes`, `run`),
which is the mistake the rule invites and which no compiler explains well at
3am.

What varies belongs in `env:` — which *is* templated, and never reaches the
compiler:

```yaml
language: c
env: {FLOOR: "{{ input.floor }}"}
script: |
  #include <stdlib.h>
  int main(void) { return atof(getenv("FLOOR")) >= 90 ? 0 : 1; }
```

That rule is also why there is no expiry to write: the cache is bounded by the
number of distinct scripts in the project. The toolchain's version is
deliberately not in the key — upgrading a compiler over unchanged source almost
never changes what the program does, and reading a version would cost a process
on every *hit*, which is the cost this exists to remove.

A build that fails comes back as its own exit code and the compiler's own
output, exactly as a red test suite does.

## `confirm` — the step nobody else can take

```yaml
- id: confirm
  type: confirm
  prompt: |
    Merge #{{ nodes.open_pr }}? It changes a public interface.
  choices: [merge, hold]
```

poieo's other safeguard is the worktree: a run works in a private copy, and the
morning reads the diff and accepts or discards it (see
[workspace.md](workspace.md)). That covers everything a run *writes*. It does
not cover what leaves the copy — a push, a merge, a deployment, an email, a
charge. Discarding a worktree does not unsend a message, and this is the node
for the step before one of those.

**The run ends here.** Not suspended: ended. `next:` is refused, because what
happens after the answer is the card's `then:`, one level up —

```yaml
then:
  - when: "run.answer == 'merge'"
    to: land
```

— and the answer is one more fact about a finished run, beside `run.usage`
and `run.change`. Suspending mid-walk instead would mean keeping a whole run's
scope alive until somebody woke up, and holding the task's only runner while it
waited. Ending costs neither, and the irreversible step is already its own card
in every flow that has one.

The status while it waits is **`asking`** — its own, so that a `then:` written
as `run.status == 'completed'` cannot fire underneath a question. The branch is
**deferred, not skipped**: it is evaluated the moment an answer arrives.

`choices:` is required, and two or more. One is not a decision, and free text
would put the run back to being read by `'HOLD' in text`, which is the guess
this node replaces. An answer that was not offered is refused.

**A card waiting on an answer keeps to its schedule.** That is what ending
rather than suspending buys, and it has a price: a card that asks every night
asks again tomorrow, and the older question is dropped for the newer one. Where
the work before the question is expensive, give that card
`trigger: {type: manual}` so it only wakes on a handoff.

**An outstanding question outlives the daemon.** It is written to
`runs/asking/<card>.json` when the run parks and removed the moment it is
answered, and a daemon starting up picks up whatever the last one left. That
file has to exist: a question that a restart ate would leave the decision
reachable only by running the card again, which for the card this node is
written for means doing the whole night's work a second time. It is gitignored
like the rest of `runs/`, and a file that cannot be read is a warning and no
question — the recovery is the one the user has anyway.

**Answering is still a daemon-side call.** The way to reach it from a terminal
or the board is the next slice.

### An agent node's hands

**No `tools:` line means no tools**: the node calls the model once, reads the
answer, and cannot touch a file. Tools are what bring the loop, the `workdir`
and the turn budget with them, which is why there is no separate type for a
call without them — and why hands are asked for rather than defaulted.

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

Among those names are `run.usage` and `run.elapsed`, which is how a router
stops a run that has spent or lasted too long — the guard an unattended run
needs, since `max_steps` counts steps and an agent node with tools is one step
however long it stays inside. See [runtime.md](runtime.md).

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
