# Web Frontend Implementation Plan (Plan B)

**Goal:** Point a browser at `http://127.0.0.1:8484` while `poieo daemon` runs and watch the work happen — which flow is on which node, every tool call as it fires, what the model said and thought each turn — and replay any past run the same way.

**Architecture:** One reducer (`StageState`) folds the event stream into a presentation-neutral model; skins render that model and nothing else. Live SSE and replayed history run through the same reducer, so replay is the live path at a different speed. `ledger` (plain DOM) is the default skin; the review screen — work list, diff, accept/discard — is shared React UI outside the skins. *(See the amendment: `atelier` is optional and last.)*

**Tech Stack:** Vite + React + TypeScript, vitest for the reducer, PixiJS for `atelier`. Node v24.14.0 / npm 11.9.0 on this machine.

**Spec:** docs/specs/2026-08-22-web-observation-design.md

**Depends on:** Plan A, merged to main at `87c01fb`. Its API is live and verified by curl; nothing in this plan changes backend behaviour except the one static-mount fix in Task 1.

---

## Amendment 2026-08-22 — the review screen comes first

`docs/specs/2026-08-22-nightly-review-design.md` resequenced this
plan. The first question the page must answer is not *what is it doing* but
**what did it do last night, and do I want it** — so the review screen is now
part of v1 and `atelier` is not.

What changes:

- **Three new tasks, 5A–5C**, inserted after Task 5: the work list, the diff
  viewer, and the accept/discard controls. They are numbered this way so the
  existing tasks keep their numbers and their briefs stay valid.
- **Task 6 (`atelier`) is now optional and last.** Ship 1–5C, 7 and the product
  is usable; `atelier` is charm on top and may be dropped from this plan
  entirely without anything else changing. The skin contract is unaffected —
  that was the point of having it.
- **`ledger` is the default skin** (Task 4 already builds it; Task 6's registry
  line no longer makes `atelier` default).
- **The read-only constraint below now has exactly two exceptions**: accept and
  discard, in Task 5C. Nothing else may POST. See the vocabulary rule.

**Depends additionally on:** Plan C (checkpoint backend), which provides
`GET /api/runs/{id}/diff`, `POST /api/flows/{flow}/accept`,
`POST /api/flows/{flow}/discard`, `pending` on `GET /api/flows`, and the
`change` key on run summaries. Tasks 5A–5C cannot start before it is merged.

**Vocabulary rule (binding on all UI text in this plan):** the user sees
**task**, **work**, and **change**. The strings `commit`, `sha`, `branch`,
`worktree`, `ref`, `merge`, `HEAD` and `run id` must not appear in rendered
text. One licensed exception: the accept button's preview line, which says
what is about to happen to the user's own repository — `adds 3 commits to
main`. A test asserts the forbidden words are absent from the rendered board.

---

## Event vocabulary (verified against `src/poieo/`)

Every event dict is `{run_id, type, at, node_id?, data}` — `node_id` is omitted when null (`Event.as_dict` drops `None`). SSE frames are `data: <that dict>\n\n`, byte-identical to the JSONL lines, which is what makes replay and live the same code path.

| `type` | `node_id` | `data` | emitted by |
|---|---|---|---|
| `run_started` | — | `graph, flow, trigger, iteration, binding, input` | `executor.py:70` |
| `node_started` | yes | `type, step` | `executor.py:98` |
| `node_finished` | yes | `step, next, output` + node meta (`role, binding, model, usage, stop_reason`, agent nodes add `turns, tool_calls`) | `executor.py:103` |
| `node_turn` | yes | `turn, text, thinking, tool_call_count` | `nodes.py:200` |
| `node_tool_call` | yes | `turn, name, arguments, result, error, duration_ms` | `nodes.py:236` |
| `run_finished` | — | `steps, usage, path` | `executor.py:140` |
| `run_failed` | maybe | `error` | `executor.py:113` |
| `run_aborted` | — | `reason` | `executor.py:110` |

One frame breaks the shape, deliberately — `run_summary` is published **flat** by `BroadcastStore.record_summary` (`web/events.py:54`):

```
{type: "run_summary", run_id, flow, graph, status, started_at, finished_at, steps, iteration, usage, error}
```

It is live-only: summaries go to `index.jsonl`, not to the run's own JSONL, so `/api/runs/{id}` never returns one. The reducer must read `run_summary` fields off the top level, not off `data`.

**Which flow does an event belong to?** Only `run_started.data.flow` and `run_summary.flow` carry it. The client keeps its own `run_id -> flow` map, seeded from `run_started`. Events for an unknown run are ignored — that is also how ad-hoc `poieo run` executions (which have `flow: null`) stay off the board, per the spec's out-of-scope list.

## API surface (as built)

| route | returns |
|---|---|
| `GET /api/flows` | `{flows: [{name, graph, trigger, status, current_run_id, last_run}]}` — `last_run` is a run summary or `null` |
| `GET /api/runs?flow=&limit=20` | `{runs: [summary, ...]}` newest first |
| `GET /api/runs/{run_id}` | `{run_id, events: [...]}`, or 404 `{error}` |
| `GET /api/events?flow=` | SSE, `text/event-stream` |
| `GET /` | `static/index.html` if built, else a plaintext "not built yet" line |

Added by Plan C, consumed by Tasks 5A–5C:

| route | returns |
|---|---|
| `GET /api/runs/{run_id}/diff` | `{run_id, base, head, files, patch, truncated}`, or `{change: null}` when the run changed nothing |
| `POST /api/flows/{flow}/accept` | `{accepted: n}` / 409 `{conflict: [...]}` / 409 `{dirty: [...]}` |
| `POST /api/flows/{flow}/discard` | `{discarded: n}` |

`GET /api/flows` also gains `pending: n`, and run summaries gain an optional `change` key.

## Global Constraints

- New npm dependencies only, in `web-ui/`: react, react-dom, typescript, vite, @vitejs/plugin-react, vitest, pixi.js, and their types. No state library, no router, no CSS framework, no component kit, no sprite/art packages — the spec puts asset packs out of scope and `atelier` is drawn from shapes in code.
- **PixiJS is loaded lazily.** It is by far the heaviest thing that reaches the browser, and it serves exactly one skin. `atelier` reaches it through a dynamic `import("pixi.js")`, which Vite splits into its own chunk — someone who stays on `ledger` never downloads it. Nothing outside `skins/atelier/` may import pixi statically; a static import silently folds it back into the main bundle.
- **No new pip dependencies.** The only Python change in this plan is the `/assets` mount fix in Task 1.
- **Read-only, with exactly two exceptions.** Only `review/Decide.tsx` (Task 5C) may issue a non-GET request, and only to accept and discard. No other component may POST, PUT, PATCH or DELETE. Skins may never do so at all.
- Built output is **checked in** at `src/poieo/web/static/` (spec: "built frontend (checked in; `npm run build` refreshes it)"). `web-ui/node_modules/` is not.
- Skins never touch the API and never see a raw event — they receive `StageState` and callbacks. Any skin reaching for `fetch` is a bug in the design, not a shortcut.
- `prefers-reduced-motion` is respected: `atelier` switches to instant state changes, no tweens.
- Python test command on this machine (broken global pytest plugin): `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio`. Full suite currently passes **171**.
- Frontend test command: `npm test --workspace web-ui` (vitest in run mode, not watch — watch mode hangs an agent).
- Commit messages end with the trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Comment style: sparse, like the Python modules — explain constraints, not mechanics.

---

### Task 1: Vite scaffold, npm workspace, and static-serving wiring

**Files:**
- Create: `package.json` (repo root, workspace declaration only)
- Create: `web-ui/` (Vite scaffold: `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.tsx`, `src/App.tsx`)
- Modify: `src/poieo/web/server.py` (the `/assets` mount)
- Modify: `.gitignore`
- Test: `tests/test_web_server.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `npm run build --workspace web-ui` writes `src/poieo/web/static/{index.html,assets/*}`; the daemon serves it at `/`. `npm run dev --workspace web-ui` serves on 5173 and proxies `/api` to 8484.

**The bug this task fixes.** `server.py:97` currently mounts `StaticFiles(directory=STATIC_DIR)` at `/assets`, so a request for `/assets/index-abc.js` resolves to `static/index-abc.js`. Vite emits `static/assets/index-abc.js` and references it as `/assets/index-abc.js` — the current wiring 404s on every asset. Point the mount at `STATIC_DIR / "assets"` instead. This was never caught because `static/` does not exist yet, so the `is_dir()` guard skips the mount entirely.

- [ ] **Step 1: Scaffold**

```bash
npm create vite@latest web-ui -- --template react-ts
npm install --workspace web-ui pixi.js
npm install --workspace web-ui -D vitest
```

Root `package.json` — a workspace host, nothing else:

```json
{
  "name": "poieo-workspace",
  "private": true,
  "workspaces": ["web-ui"]
}
```

`web-ui/package.json` scripts: `"test": "vitest run"`.

`web-ui/vite.config.ts`:

```ts
export default defineConfig({
  plugins: [react()],
  // The daemon serves this from its own package; build straight into it so
  // `npm run build` is the only publish step.
  build: { outDir: "../src/poieo/web/static", emptyOutDir: true, assetsDir: "assets" },
  server: { proxy: { "/api": "http://127.0.0.1:8484" } },
})
```

Record the resolved versions of vite/react/pixi in the commit message — `npm create vite@latest` moves.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_web_server.py`, following that file's existing `TestClient` pattern:

```python
def test_assets_mount_serves_the_vite_asset_dir(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>poieo</title>")
    (static / "assets" / "app.js").write_text("export default 1;\n")
    monkeypatch.setattr(server, "STATIC_DIR", static)

    client = TestClient(server.create_app(<the file's fake daemon>))
    assert client.get("/").status_code == 200
    # Vite's index.html references /assets/<name>; the mount must resolve there
    assert client.get("/assets/app.js").status_code == 200
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_web_server.py -q -p asyncio -k assets`
Expected: FAIL — 404 on `/assets/app.js`.

- [ ] **Step 4: Implement**

In `src/poieo/web/server.py`, replace the mount block:

```python
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        routes.append(Mount("/assets", StaticFiles(directory=assets), name="assets"))
```

`STATIC_DIR` must be read at call time inside `create_app`, not captured at import — the test monkeypatches the module attribute.

In `.gitignore`, add `node_modules/` and `web-ui/dist/`. Do **not** ignore `src/poieo/web/static/`.

- [ ] **Step 5: Verify the round trip**

```bash
npm run build --workspace web-ui
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio
python main.py daemon examples/poieo.yaml &
curl -s http://127.0.0.1:8484/ | head -3
```

Expected: full Python suite passes (172); `/` returns the Vite HTML, not the "not built yet" line. Paste the output into the report.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json web-ui .gitignore src/poieo/web/server.py tests/test_web_server.py src/poieo/web/static
git commit -m "feat: vite frontend scaffold served by the daemon"
```

---

### Task 2: `api.ts` — fetch helpers and the event feed

**Files:**
- Create: `web-ui/src/api.ts`
- Create: `web-ui/src/types.ts`
- Test: `web-ui/src/api.test.ts`

**Interfaces:**
- Consumes: the routes in "API surface" above.
- Produces:
  - `types.ts`: `PoieoEvent`, `RunSummary`, `FlowRow` mirroring the tables above.
  - `fetchFlows(): Promise<FlowRow[]>`, `fetchRuns(opts?): Promise<RunSummary[]>`, `fetchRunEvents(runId): Promise<PoieoEvent[]>`.
  - `openFeed(handlers): () => void` — wraps `EventSource("/api/events")`, parses each frame, hands a `PoieoEvent` to `handlers.onEvent`, reports connection state via `handlers.onStatus("connecting" | "live" | "lost")`, returns a close function.

**The resync rule.** EventSource reconnects on its own, but the gap while it was down is real. On `open` — the first one and every reconnect — the caller is told to resync: `openFeed` calls `handlers.onResync()`, and App re-fetches `/api/flows` plus `/api/runs/{current_run_id}` for any flow that is mid-run, feeding those events through the same reducer. Duplicates are the reducer's problem (Task 3), not this module's.

- [ ] **Step 1: Write the failing tests**

`web-ui/src/api.test.ts` — stub `globalThis.fetch` and a minimal fake `EventSource`:

```ts
test("fetchFlows unwraps the envelope", ...)          // {flows: [...]} -> [...]
test("fetchRunEvents returns [] for a 404 run", ...)  // a missing run is not an exception
test("openFeed parses frames and reports status", ...)
test("openFeed calls onResync on every open, not just the first", ...)
test("the close function detaches and stops delivery", ...)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test --workspace web-ui`
Expected: FAIL — `src/api.ts` does not exist.

- [ ] **Step 3: Implement**

Keep it thin: no retry logic of our own (EventSource has it), no caching, no abort controllers beyond the returned close function. `fetchRunEvents` maps 404 to `[]` because a fresh daemon legitimately has no runs — the spec calls for "an empty board with an invitation, not an error".

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test --workspace web-ui`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: web-ui api client and SSE feed"
```

---

### Task 3: `StageState` — interpret once, render many ways

**Files:**
- Create: `web-ui/src/state/stage.ts`
- Create: `web-ui/src/state/fixtures.ts` (event fixtures captured from real mock-binding runs)
- Test: `web-ui/src/state/stage.test.ts`

**Interfaces:**
- Consumes: `PoieoEvent`, `FlowRow`.
- Produces:

```ts
type Worker = {
  status: "waiting" | "running" | "error"
  currentNode: string | null
  nodeType: string | null
  step: number
  turn: number
  lastText: string
  lastThinking: string
  recentToolCalls: {name: string; error: string | null; at: string}[]  // newest first, cap 8
  lastRun: {status: string; steps: number; finished_at: string} | null
}
type StageState = {
  workers: Record<string, Worker>
  runFlow: Record<string, string>   // run_id -> flow, learned from run_started
  seen: Set<string>                 // dedup keys, see below
}

initialStage(flows: FlowRow[]): StageState
reduce(state: StageState, event: PoieoEvent): StageState
replay(state: StageState, events: PoieoEvent[]): StageState
```

**Dedup.** The catch-up fetch and the live feed overlap, and events carry no order index. Key each event as `` `${run_id}|${type}|${node_id ?? ""}|${data.step ?? data.turn ?? ""}|${at}` `` and drop repeats. A duplicate is the *same* event seen twice, so it matches on every field including the millisecond timestamp; two genuinely different events always differ in type, node, step or turn. Prune `seen` when a run ends, or it grows for the daemon's lifetime.

**Per-event behaviour:**

| event | effect |
|---|---|
| `run_started` | learn `runFlow[run_id] = data.flow`; if `data.flow` is null or unknown, ignore this and every later event for the run. Set worker `status: "running"`, reset `step`, `turn`, `recentToolCalls` |
| `node_started` | `currentNode = node_id`, `nodeType = data.type`, `step = data.step`, `turn = 0` |
| `node_turn` | `turn = data.turn`, `lastText = data.text`, `lastThinking = data.thinking` |
| `node_tool_call` | unshift `{name, error, at}`, cap at 8 |
| `node_finished` | leave `currentNode` alone — the next `node_started` replaces it; the board should not blink to empty between nodes |
| `run_finished` | `status = "waiting"`, `currentNode = null` |
| `run_failed` / `run_aborted` | `status = "error"`, `currentNode = null` |
| `run_summary` | `lastRun = {status, steps, finished_at}` — **flat fields, not `data`**; forget the `runFlow` entry and its `seen` keys |
| anything else | return state unchanged (forward compat: a new backend event must never break an old build) |

`reduce` is pure and returns a new object when something changed, the same reference when nothing did — the App only re-renders on identity change.

- [ ] **Step 1: Capture fixtures**

```bash
python main.py daemon examples/poieo.yaml --once --flow revision
```

Copy the resulting `examples/.poieo/runs/<run_id>.jsonl` lines into `fixtures.ts` as a typed array, plus a hand-written `run_summary` frame (the store does not put summaries in that file) and one agent run captured from `examples/tasks/agent-task.graph.yaml` so `node_turn` and `node_tool_call` are covered with real `thinking` text:

```bash
python main.py run examples/tasks/agent-task.graph.yaml -b examples/models/mock.yaml \
  --set workdir=<a scratch dir> --store <a scratch store>
```

- [ ] **Step 2: Write the failing tests**

```ts
test("a full run walks waiting -> running -> waiting", ...)
test("node_turn records text and thinking", ...)
test("tool calls accumulate newest-first and cap at 8", ...)
test("node_finished does not clear the current node", ...)
test("run_failed puts the worker in error", ...)
test("run_summary reads flat fields and fills lastRun", ...)
test("replaying history then applying the live overlap is idempotent", ...)  // the dedup rule
test("events for an unknown run are ignored", ...)                          // ad-hoc poieo run
test("an unknown event type leaves the state untouched", ...)
test("replay(initial, fixture) equals folding the fixture one at a time", ...)
```

- [ ] **Step 3: Run tests to verify they fail**

- [ ] **Step 4: Implement**

- [ ] **Step 5: Run tests to verify they pass**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: StageState reducer folds run events into a stage model"
```

---

### Task 4: Skin contract and the `ledger` skin

**Files:**
- Create: `web-ui/src/skins/contract.ts`
- Create: `web-ui/src/skins/registry.ts`
- Create: `web-ui/src/skins/ledger/index.ts`
- Create: `web-ui/src/skins/ledger/ledger.css`
- Test: `web-ui/src/skins/registry.test.ts`

**Interfaces:**
- Consumes: `StageState`.
- Produces, verbatim from the spec:

```ts
interface Skin {
  id: string
  label: string
  mount(el: HTMLElement, callbacks: {onSelectWorker(flow: string): void}): SkinHandle
}
interface SkinHandle {
  update(stage: StageState): void
  destroy(): void
}
```

`registry.ts` exports `SKINS: Skin[]` and `skinById(id): Skin` falling back to `ledger` — an unknown id in localStorage must not blank the page. The registry holds skin *descriptors*, so listing skins in the picker must not pull any skin's rendering code — `atelier`'s id and label are known without loading PixiJS.

**`mount` stays synchronous**, exactly as the spec writes it, even though `atelier` loads its renderer asynchronously. A skin that needs something loaded returns its handle immediately, keeps the latest `StageState` handed to `update()`, and swaps in the real renderer when the load resolves. The alternative — making `mount` return a promise — would push waiting into the App and into every future skin to serve one skin's private problem.

`ledger` is deliberately plain DOM (no React, no canvas): one card per flow with a live status dot, the current node and step, the latest turn's text, and a scrolling feed of turns and tool calls. It is the fallback and the proof that the contract is sufficient — if `ledger` needs something `StageState` does not carry, the reducer is wrong, not the skin.

- [ ] **Step 1: Write the failing tests**

```ts
test("every registered skin satisfies the contract", ...)     // id, label, mount present
test("skinById falls back to ledger for an unknown id", ...)
test("mount/update/destroy leaves the element empty", ...)    // no leaked nodes or listeners
test("ledger renders one card per worker and reflects status", ...)  // jsdom
test("listing skins loads no renderer", ...)   // the picker must not drag PixiJS in
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: skin contract and the ledger skin"
```

---

### Task 5: App shell — skin picker and detail drawer

**Files:**
- Create: `web-ui/src/detail/Drawer.tsx`
- Modify: `web-ui/src/App.tsx`
- Modify: `web-ui/src/main.tsx`
- Test: `web-ui/src/App.test.tsx`

**Interfaces:**
- Consumes: `api.ts`, `stage.ts`, `registry.ts`.
- Produces: the shell that owns all state — it mounts the selected skin into a div it controls, feeds it `StageState` on every change, and renders the drawer outside the skin.

**Behaviour:**
- On load: `fetchFlows()` seeds `initialStage`, then `openFeed`.
- On every feed open/reopen: re-fetch flows, and for each flow with a `current_run_id`, `fetchRunEvents` and `replay` it — so a browser that arrives mid-run, or reconnects after a drop, catches up without a gap.
- Skin selection persists in `localStorage` under `poieo.skin`; changing it calls `destroy()` on the old handle before mounting the new one, then immediately pushes the current stage so the new skin is not blank until the next event.
- `onSelectWorker(flow)` opens the drawer: that worker's turn timeline (text plus collapsed thinking), its tool calls with errors and durations, and its recent runs from `fetchRuns({flow})`, each replayable — selecting a past run replays it through the reducer into a *separate* stage instance so the live board is untouched.
- Connection state ("live" / "reconnecting") shows in a corner. Zero flows shows the invitation, not an error.

- [ ] **Step 1: Write the failing tests**

```ts
test("seeds from /api/flows then subscribes", ...)
test("a resync replays the in-flight run before live events", ...)
test("skin choice persists and survives an unknown stored id", ...)
test("switching skins destroys the old handle exactly once", ...)
test("selecting a worker opens the drawer with its turns", ...)
test("replaying a past run does not disturb the live stage", ...)
test("no flows renders the invitation, not an error", ...)
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Manual check**

```bash
npm run dev --workspace web-ui        # 5173, proxying /api to 8484
python main.py daemon examples/poieo.yaml
```

Open 5173 with `ledger` selected: the revision flow should tick every ~10s, cards should change status, and the drawer should open on click. Report what you saw.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: app shell, skin picker, and detail drawer"
```

---

### Task 5A: the work list

**Files:**
- Create: `web-ui/src/review/WorkList.tsx`
- Create: `web-ui/src/review/rollup.ts`
- Modify: `web-ui/src/state/stage.ts` (night rollup per flow)
- Test: `web-ui/src/review/rollup.test.ts`, `web-ui/src/review/WorkList.test.tsx`

**Interfaces:**
- Consumes: `GET /api/runs?flow=` summaries, each optionally carrying `change`.
- Produces: `rollup(summaries) -> {works, succeeded, failed, nothingToDo, insertions, deletions}` for the card line, and a list component rendering one row per piece of work.

**Rows read:** time, outcome, size (`+42 / -11 · 3 files`), and the model's own
one-line summary. Outcomes are **succeeded / failed / found nothing to do** —
a run that changed nothing is not a failure and must not be counted as one.
Failed rows are collapsed behind a single "2 failed" line by default.

- [ ] **Step 1: Write the failing tests**
  - `rollup` over fixtures: counts, sums, and a run with no `change` contributing zero lines but still counting as work
  - an empty night renders an invitation, not an error
  - failed rows are collapsed until expanded
  - **no forbidden vocabulary** in the rendered output (the amendment's rule, asserted here once for the review UI)
- [ ] **Step 2: Run to verify they fail** — `npm test --workspace web-ui`
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run tests** — [ ] **Step 5: Commit** — `feat: last night's work, as a list`

---

### Task 5B: the diff viewer

**Files:**
- Create: `web-ui/src/review/Diff.tsx`
- Modify: `web-ui/src/api.ts` (`fetchDiff(runId)`)
- Test: `web-ui/src/review/Diff.test.tsx`

**Interfaces:**
- Consumes: `GET /api/runs/{run_id}/diff` → `{base, head, files, patch, truncated}`.
- Produces: a per-file folded diff. No syntax highlighting, no new dependency — a unified patch split by file, added and removed lines coloured.

- [ ] **Step 1: Write the failing tests**
  - files render folded, with per-file `+n / -n`; clicking one expands its hunks
  - `truncated: true` shows the file list plus an honest line saying the patch was too large to display in full — it does not silently show a partial diff as if it were whole
  - `change: null` (a run that changed nothing) renders "this work changed no files", not an empty box
  - a fetch failure renders a retry, not a blank pane
- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run tests** — [ ] **Step 5: Commit** — `feat: read a piece of work as a diff`

---

### Task 5C: accept and discard

**Files:**
- Create: `web-ui/src/review/Decide.tsx`
- Modify: `web-ui/src/api.ts` (`accept(flow, throughRunId?)`, `discard(flow, fromRunId?)`)
- Modify: `web-ui/src/review/WorkList.tsx` (per-work controls)
- Test: `web-ui/src/review/Decide.test.tsx`

**Interfaces:**
- Consumes: the two POST routes from Plan C, plus `pending` from `GET /api/flows`.
- Produces: card-level *accept last night's work* / *discard last night's work*, and per-work *accept up to this work* / *discard from this work onward*. There is deliberately no "accept only this one" — acceptance is linear.

**These are the only two components in the app permitted to make a
non-GET request.** Everything else stays read-only, and the constraint list
above still holds for them.

- [ ] **Step 1: Write the failing tests**
  - accept posts once, then refetches flows and runs; the card shows nothing pending
  - a 409 `{"dirty": [...]}` renders "you have uncommitted changes in *files*; commit or stash them first" and leaves the list as it was
  - a 409 `{"conflict": [...]}` names the files and says the user changed them too — it does not offer a resolve button
  - discard asks for confirmation once, and the confirmation says the work is thrown away — not that it is deleted forever, which would be a lie
  - the accept preview line renders the count against the user's branch (`adds 3 commits to main`), the one place git words are allowed
  - buttons disable while the request is in flight; a double click cannot post twice
- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run tests** — [ ] **Step 5: Commit** — `feat: accept or throw away last night's work`

---

### Task 6: the `atelier` skin *(optional — ship 7 without it if time is short)*

**Files:**
- Create: `web-ui/src/skins/atelier/index.ts`
- Create: `web-ui/src/skins/atelier/scene.ts` (shape drawing: bench, figure, tool wall, shelf)
- Modify: `web-ui/src/skins/registry.ts` (register it; `ledger` stays the default)
- Test: `web-ui/src/skins/atelier/scene.test.ts`

**Interfaces:**
- Consumes: `StageState`, PixiJS — **only** through `await import("pixi.js")` inside `index.ts`.
- Produces: a skin satisfying the same contract as `ledger` — no new state, no API access.

**Lazy loading, concretely.** `mount()` returns its handle at once, having painted a quiet "opening the workshop" placeholder and started the import. Until it resolves, `update(stage)` just stores the stage. When it resolves, the renderer is built and immediately fed the stored stage — so a skin switch mid-run shows the current state, not a blank bench waiting for the next event. If `destroy()` lands before the import resolves, a disposed flag makes the resolution a no-op: no PixiJS canvas may appear in a detached element. A failed import (offline, corrupt chunk) leaves a plain message in place and logs — it must not take the page down, since the page's whole job is showing that something else is still running.

**The scene, per the spec.** An isometric workshop drawn from shapes in code; no sprite packs. One workbench per flow, with an artisan figure that:

| stage | scene |
|---|---|
| `status: waiting` | figure sits, bench lamp dimmed |
| `status: running` | figure works at the bench; the current node's name and type read off the bench |
| `node_tool_call` arrives | figure reaches to the wall of tools, the tool name appears briefly, an errored call flashes it red |
| `lastThinking` non-empty | a thought bubble over the figure; click → `onSelectWorker` |
| `lastRun.status === "completed"` | a finished piece is stamped and shelved |
| `status: error` | red warning lamp |

Quiet ambient motion throughout. `window.matchMedia("(prefers-reduced-motion: reduce)")` switches every transition to an instant state change — no tweens, no ambient loop.

**Keep the geometry testable.** Pure functions in `scene.ts` decide *what* to draw (`benchLayout(count)`, `figurePose(worker)`, `bubbleVisible(worker)`, `shelfItems(worker)`); `index.ts` does the PixiJS drawing. Only the pure half is unit-tested — the spec puts visual verification in the browser, by hand.

- [ ] **Step 1: Write the failing tests**

```ts
test("benchLayout spaces N benches without overlap", ...)
test("figurePose maps waiting/running/error to distinct poses", ...)
test("bubbleVisible is false when thinking is empty", ...)
test("a tool call surfaces the tool name and its error flag", ...)
test("shelfItems grows only on a completed run", ...)
test("reduced motion returns zero-duration transitions", ...)
test("mount returns a handle before the import resolves", ...)
test("the stage handed over while loading is applied once ready", ...)
test("destroy before the import resolves leaves nothing behind", ...)
test("a failed import degrades to a message, not a throw", ...)
```

Stub the dynamic import in these tests (`vi.mock("pixi.js", ...)`) — vitest must never load real PixiJS, and the pure `scene.ts` half needs no canvas at all.

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Manual check**

Run the dev server against a daemon with `examples/tasks/agent-task.graph.yaml` wired into a flow so tool calls and thinking actually appear. Confirm: bubble on the mock worker's first turn (`"First see what is in this directory."`), the reach-to-wall on `list_dir` and `write_file`, a piece shelved at the end. Then reload with reduced motion forced on. Report what you saw.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: atelier skin"
```

---

### Task 7: build, check in, and document

**Files:**
- Modify: `README.md`
- Modify: `src/poieo/web/static/` (rebuilt output)
- Modify: `DESIGN.md` (status line only, if it tracks slices)

**Interfaces:** none — this task ships what the previous six built.

- [ ] **Step 1: Build and check in**

```bash
npm run build --workspace web-ui
git add src/poieo/web/static
```

- [ ] **Step 2: Update README.md**

Extend the observation paragraph added in Plan A: the page ships built, `npm run build --workspace web-ui` refreshes it, `npm run dev --workspace web-ui` proxies to a running daemon, and skins are switchable in the corner. Match the README's plain tone; three or four sentences.

- [ ] **Step 3: Full suite, both sides**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio
npm test --workspace web-ui
```

Expected: both green.

- [ ] **Step 4: Verify the PixiJS chunk really is separate**

```bash
npm run build --workspace web-ui
ls -la src/poieo/web/static/assets
```

Expected: an entry chunk and a distinctly larger pixi chunk beside it. Grep the entry chunk for a PixiJS-only identifier to prove it is absent — if PixiJS folded into the entry, some module imported it statically. Record both chunk sizes in the report; they are the number this decision was made on.

- [ ] **Step 5: End-to-end smoke**

```bash
python main.py daemon examples/poieo.yaml
```

Open `http://127.0.0.1:8484` in a browser — not the dev server. Confirm the built page loads from the daemon, both skins run, and the drawer replays a past run. Paste what you saw into the report.

- [ ] **Step 6: Commit**

```bash
git commit -m "docs: build and document the observation UI"
```

---

## Done means

- **The morning works:** open `127.0.0.1:8484`, see last night in one line per task, open a piece of work, read its diff, and accept or throw it away — without touching a terminal.
- A user who never learns the word "commit" can do all of the above, and the rendered text proves it.
- `poieo daemon examples/poieo.yaml` and a browser at `127.0.0.1:8484` shows flows moving in real time, in either skin, with no build step required of the user.
- The reducer has fixture-driven tests; replay and live provably agree.
- A third skin would be one new module and one registry line — no backend change, no reducer change.
- Staying on `ledger` downloads no PixiJS at all, and the entry chunk proves it.
