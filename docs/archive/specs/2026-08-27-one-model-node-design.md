# One Model Node Design

**Date:** 2026-08-27
**Status:** Approved for planning

## Goal

There are three node types and two of them are the same node.

`LLMNode` and `AgentNode` share their prompt rendering (`_prepare`), their
retry (`call_with_retry`) and their output handling (`_finish`). Everything
that differs follows from one thing: whether the model is shown any tools.

- offered tools, so it may ask for one, so there has to be a loop (`max_turns`)
- offered tools, so there has to be a directory for them to work in
- offered tools, so an executor is built, and turns are emitted

`llm` is `agent` with no tools. Keeping it as a separate type spends a word of
principle 7's budget on a distinction the `tools:` line already makes.

It also leaves a trap. `NodeSpec.max_turns` allows 1, and `agent` with
`max_turns: 1` offers tools and then **fails the run if the model uses one** —
a third thing that is neither `llm` nor `agent` and that nobody means. With one
node type it cannot be expressed.

## 1. What is left

Two node types: **`agent`** and **`router`**. A node either does work or picks
a path.

```yaml
# no tools: what `type: llm` used to be
- id: classify
  type: agent
  role: classifier
  prompt: "Classify {{ input.message }}"
  output: {as: category}
  next: route

# with tools: what `type: agent` used to be
- id: work
  type: agent
  role: worker
  prompt: "Fix the failing test"
  tools: [files, shell]
  workdir: .
  max_turns: 20
```

## 2. Absent `tools:` means no tools

This is the one behaviour change, and it is the safe direction.

Today a graph's `agent` node that says nothing about tools gets `files` and
`shell` — the model has hands because it did not say otherwise. Once `llm` is
gone, that default would apply to every model call in every graph, and
*forgetting a line* would hand out hands. That is exactly backwards.

Principle 2 already settles it for the folder:

> the folder stays explicit on purpose: it is the one thing the model's hands
> will touch, and that moment must never be filled in by a default

Hands themselves are the same rule one level up. So: **no `tools:` line, no
tools.** A node that wants to touch the project says so, and the diff of any
graph shows at a glance which of its steps can.

`DEFAULT_TOOLSETS` stays where it belongs — `task.expand()`, where a card that
names no tools gets `files` and `shell`. A task card *is* a request for hands
in a folder; a graph node is not.

`examples/tasks/agent-task.graph.yaml` gains the `tools:` line it was relying
on a default for. That is the only place in the repo that was.

## 3. A workdir is required only when tools are

`needs_a_workdir` becomes "agent nodes **with tools** and no workdir". A model
that only reads a prompt and answers has nothing to do with the filesystem,
which is what lets a text-only flow — `revision` in `examples/poieo.yaml`, with
no `workdir:` anywhere — keep working.

## 4. What goes away

- `LLMNode`, and the `llm` entry in `NODE_TYPES`
- the `llm` arm of `NodeSpec._check_shape`, and with it the rule that an `llm`
  node may not name `workdir` or `tools` — there is no such node to refuse
- `type: llm` in every graph, example, and test: **one word, mechanically**

`max_turns: 1` stops being a trap without a rule against it: with no tools
there is nothing to leave pending, and a node that has tools and one turn is
now visibly a node that has tools and one turn.

## Out of scope

- **Renaming `agent`.** A node with no tools reading as "agent" is a fair
  complaint, and `step` or `model` would read better. It is also a second edit
  to every file this one already touches, and it is reversible later; doing
  both at once would make the diff unreadable.
- **A deterministic node** (`run` / `command`) for work that needs no model.
  The empty quadrant, and its own design.
- **Opening `NodeSpec.type` to a registry.** `NODE_TYPES` is already a dict and
  `build_node` already looks up in it; only the schema's `Literal` is closed.
  Worth doing when three cases need it, not before.
