# Graph

`src/poieo/graph.py`, `src/poieo/expr.py`

A graph describes what a run does and how control moves between steps. Agent
nodes name roles, never providers or models; a [binding](binding.md) supplies
that physical choice. Graph and node models reject unknown keys.

## Graph shape

```yaml
name: review-and-fix
version: 1
entry: review
max_steps: 100
default_role: default
state: {attempts: 0}

nodes:
  - id: review
    type: agent
    role: reviewer
    prompt: "Review {{ input.request }}."
    output: {as: findings, format: text}
    next: decide

  - id: decide
    type: router
    branches:
      - when: findings != ""
        to: fix
    default: done

  - id: fix
    type: agent
    role: writer
    prompt: "Fix these findings: {{ findings }}"

  - id: done
    type: command
    command: echo nothing to fix
```

`GraphSpec` contains `name`, `version`, optional `description`, `entry`,
`nodes`, seed `state`, `max_steps`, and `default_role`. Node ids are
alphanumeric with `-` and `_` allowed, and may not start with a digit. Loading
rejects duplicate ids, missing entry or targets, unreachable nodes, invalid
node-specific fields, and invalid templates or expressions. Cycles are allowed;
`max_steps` bounds them at run time.

## Node contracts

All nodes may have a description, output rule, and `next` where the node type
allows it.

### `agent`

An agent renders `system` and `prompt`, resolves its role through the binding,
and requests a completion. It may declare generation `params`, `retry`,
`workdir`, `tools`, `max_turns`, and `deadline`.

No `tools` field means no tools for an explicit graph node. An empty list also
means no tools. Tool results are fed back to the model until it gives a final
answer or reaches its turn, deadline, context, or cancellation boundary.

### `command`

A command node declares exactly one of:

- a one-line `command`; or
- `script` plus a known `language`.

It may also set `timeout`, `env`, `workdir`, output, and `next`. Commands and
scripts go through the same [executor](tools.md) used by model tools, so task
isolation cannot be bypassed. Interpreted scripts are rendered as templates.
Compiled script source is the build-cache key and is therefore not templated;
varying input belongs in `env`.

A nonzero exit code is output data, not a failed run. Failure means the command
could not start, timed out, or violated the executor contract. Routers can branch
on the numeric exit code.

### `router`

A router evaluates `branches` in order and chooses the first true `when`.
`default` is used when none match. It calls no model and has no `next`; its
selected target is the successor.

Selecting nothing is how a graph stops on a condition, so both ways of doing it
end the run: a matched branch with no `to`, and no branch matching when there is
no `default`.

### `confirm`

A confirm node renders a question and presents at least two distinct fixed
choices. It ends the run with status `asking`; it never names a successor. The
answer is persisted and any task-level `then` branches decide what task runs
next. See [daemon.md](daemon.md).

A private Git workspace can undo file changes, but it cannot unsend a message,
reverse a deployment, cancel a charge, or undo another external effect. Put a
confirm node before that boundary and place the effect in the downstream task
selected by `then`; discarding the earlier workspace is not a substitute.

## Output and scope

An output rule may name an alias with `as`, parse the value as `text` or `json`,
select a dotted `path` inside parsed JSON, and place the result under a key in
persistent `state`. `path` does not write a file. Aliases make later templates
and expressions concise; state is the data that may be carried into the task's
next run.

Templates and expressions see public run data only:

- `input` — the run input;
- `state` — graph state;
- `nodes` — completed node outputs;
- `run` — id, task, trigger, iteration, path, usage, and elapsed time;
- output aliases.

Templates use `{{ expression }}`. Conditions use the same names through a
restricted expression evaluator. It permits public attribute access on plain
run data and calls to approved built-ins or public methods on that data. Private
and dunder names, imports, lambdas, comprehensions, assignment, and arbitrary
Python objects are rejected. YAML `true`, `false`, and `null` are accepted;
expression length and exponent size are bounded.

## Failure and retry

Graph validation and role preflight happen before execution. During a run, a
node failure becomes a failed result with a cause suitable for a person to act
on. Agent retry wraps a whole completion attempt and applies only to failures
classified as retryable; provider transport retries remain inside the provider.
Output parsing and writing happen before the next node, so a bad declared output
cannot be mistaken for success.

## Extending graphs

A new node type needs a validated shape, a runtime implementation registered in
the node registry, event and result semantics, and a decision about which scope
data it may expose. It must not call providers, subprocesses, or files through a
new side door. If an existing node plus a router expresses the behavior, prefer
that composition to another node type.
