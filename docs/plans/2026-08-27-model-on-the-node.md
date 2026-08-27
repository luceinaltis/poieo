# Model On The Node — Implementation Plan

**Spec:** `docs/specs/2026-08-27-model-on-the-node-design.md`
**Branches:** `model-on-the-node-api`, `model-on-the-node-board` (one PR each)

Split the way #108 and #110 split the wiring: serve the data, then draw it.
Task 1 stands alone — the payload grows a field and nothing renders it yet,
which is exactly what #108 did for `then`/`shape`.

Gate before every merge:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio
npm test --workspace web-ui        # Task 2 only; run mode, never watch
```

---

## Task 1: the board is served which model each node would call

`web/server.py`:

- `_shape(graph)` becomes `_shape(flow)`, taking the `LoadedFlow` — the
  binding lives there (`LoadedFlow.binding`) and a `GraphSpec` does not know
  it exists. Call site becomes `_shape(runner.flow)`.
- Each node gains `"model"`: the id it would actually call, resolved the way
  `runtime/nodes.py` resolves it — `binding.resolve(node.role or
  graph.default_role).model`. Per-node `params` are not passed: they layer
  generation settings, never a different model.
- `llm` and `agent` nodes resolve; a `router` gets `None` without asking the
  binding anything.
- `BindingError` (a binding with no default to fall back on) yields `None`,
  not a 500 — the rule `_review_state` already set.
- Only the bare model id crosses the wire. Never `ProviderSpec`, never
  `base_url`, never `api_key_env`.
- The docstring's standing rule extends from "no prompts" to name the binding
  too, so the next person adding a field has the reason in front of them.

`web-ui/src/types.ts`: `NodeShape` gains `model: string | null`.

Tests (`tests/test_web_server.py`; the stub runner's `flow` gains a real
`BindingSpec`, as `graph` is already a real `GraphSpec`):

- [ ] a node naming a role reports that role's model id
- [ ] a node naming no role reports the model reached through the graph's
      `default_role`
- [ ] a router's `model` is `None`
- [ ] one graph served by two flows on different bindings reports different
      models for the same node — the spec's reason the model is drawn inside
      a border and never on the graph
- [ ] a role the binding never declares reports the default's model: what
      #112 made the daemon warn about, now visible in the payload
- [ ] a binding with no default serves `None` and a 200, not a 500
- [ ] the payload contains no `base_url` and no `api_key_env`

PR `feat: the board is served the model each node would actually call`.

---

## Task 2: the basic skin draws it

`web-ui/src/skins/basic/`:

- A flow whose nodes all resolve alike puts the model on `basic-when`,
  beside the trigger: `daily 2am · llama3.2:3b`. Visible shut as well as
  open — that is the glance the spec is for.
- A flow resolving to more than one puts `2 models` there instead, and each
  node pill carries its own id under its name, inside the border.
- A router pill carries nothing. Neither does a flow with no models at all.
- Structure, not state: the per-node id is written in `fillInside` (drawn
  once, moves only when a file does), not in `paint`. Only `basic-when` is
  touched by `paint`, which already rewrites it every frame.
- `basic.css` gets the dimmed second line; no layout change to the pill grid
  beyond what a second line needs.

Tests (`web-ui/src/skins/basic/index.test.ts`):

- [ ] every node resolving alike puts one model id on the header line, and
      the pills carry none
- [ ] two distinct models put `2 models` on the header and the id on each
      pill that has one
- [ ] a router pill carries no model
- [ ] a shape whose nodes all report `null` adds nothing to the header

PR `feat: the board says which model runs each node`.
