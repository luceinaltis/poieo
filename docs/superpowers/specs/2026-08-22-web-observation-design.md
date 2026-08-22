# Web Observation Design

**Date:** 2026-08-22
**Status:** Approved for planning
**Roadmap:** step 2 (web control plane), observation slice only

## Goal

Point a browser at a running `poieo daemon` and watch the work happen live:
which flow is running, which node it is on, every tool call as it executes,
and what the model said and thought at each turn. The same page replays any
past run from the store.

Editing and control (task cards, pause/resume, run-now) are the next slice —
this design is strictly read-only.

## Decisions already made (with the user)

- Realtime granularity: **turn level** — node/tool events plus one event per
  completed model turn carrying its text and thinking. Token streaming is
  explicitly out of scope (would require reworking all provider protocols).
- Server lives **inside the daemon** (same asyncio loop), Starlette + uvicorn.
- Transport: **SSE** (one-way observation; EventSource reconnects for free).
- Frontend: **Vite + React + TypeScript**, built output served statically by
  the daemon. PixiJS for sprite scenes.
- Presentation is a **swappable skin**: v1 ships `atelier` (workshop concept,
  default) and `ledger` (plain DOM timeline, fallback). Kitchen / office /
  transit-map skins come later without backend changes.

## Out of scope

- Any mutation: no flow control, no editing, no task-card CRUD.
- Token-level streaming.
- Auth / remote exposure — the server binds 127.0.0.1 only, no `--host`.
- Sprite asset packs — v1 atelier uses restrained shape-based isometric art
  drawn in code; no external art dependencies.
- Observing `poieo run` (ad-hoc CLI runs). Only daemon flows are live;
  ad-hoc runs still land in the store and can be replayed.

## Backend architecture

```
src/poieo/web/
  __init__.py
  events.py        BroadcastStore: wraps a RunStore, fans events out to queues
  server.py        Starlette app factory + uvicorn task on the daemon's loop
  static/          built frontend (checked in; `npm run build` refreshes it)
```

### Event fan-out

`BroadcastStore` wraps the daemon's `RunStore`: `append(event)` writes JSONL
as today, then pushes the event dict onto every subscriber queue.

- Zero subscribers → zero overhead beyond one `if`.
- Slow subscriber (queue past 1000 events) → that subscriber is dropped;
  the daemon never blocks on a browser. EventSource reconnects.
- Runtime code does not change: `ctx.emit` still just calls `store.append`.

### New event: `node_turn`

`AgentNode` emits one event per completed model turn:

```
{type: node_turn, node_id, data: {turn, text, thinking, tool_call_count}}
```

- `text`: the assistant text for that turn (truncated like tool results).
- `thinking`: best-effort. Providers capture separated reasoning into
  `LLMResponse.meta["thinking"]` — Ollama from `message.thinking`, anthropic
  by joining thinking blocks from the raw content. When providers don't
  separate it, inline `<think>…</think>` in `text` is left as-is and the UI
  renders it collapsed.
- Recorded in the JSONL like every event, so replay equals live.

### Daemon integration

- `poieo daemon config.yaml` starts the web server by default on
  `127.0.0.1:8484`; `--port N` overrides, `--no-web` disables.
- Port already in use → daemon fails at launch with a clear error.
- `FlowRunner` gains read-only fields: `status` ("waiting" | "running"),
  `current_run_id`, `last_result`. The API reads them; nothing else does.
- Web server task failure logs and dies alone — flows keep running.
- Daemon shutdown (SIGINT) closes SSE connections and the server cleanly.

### HTTP API (all read-only, all JSON except / and /api/events)

| route | returns |
|---|---|
| `GET /` | the built frontend (index.html + assets from `static/`) |
| `GET /api/flows` | flows: name, trigger description, graph name, status, current_run_id, last run summary |
| `GET /api/runs?flow=&limit=` | run summaries from `index.jsonl`, newest first |
| `GET /api/runs/{run_id}` | full event list for one run (replay) |
| `GET /api/events` | SSE stream of all events as they happen; `?flow=` filters |

SSE frames: `data: <event-json>\n\n`, event dicts identical to JSONL lines.

## Frontend architecture

```
web-ui/                    Vite + React + TS project (npm workspace at repo root)
  src/
    state/stage.ts         StageState reducer: events in, stage model out
    api.ts                 fetch + EventSource plumbing
    skins/contract.ts      the Skin interface
    skins/ledger/          plain DOM timeline skin (fallback, no PixiJS)
    skins/atelier/         workshop skin (PixiJS canvas)
    detail/                shared drawer: turn timeline, tool calls, history
    App.tsx                shell: skin mount, picker, drawer wiring
```

### StageState: interpret once, render many ways

A reducer folds the event stream into a presentation-neutral stage model:

```
StageState = {
  workers: {                     // one per flow
    [flow]: {
      status: waiting | running | error
      currentNode, nodeType, step
      turn, lastText, lastThinking
      recentToolCalls: [{name, error, at}]
      lastRun: {status, steps, finished_at}
    }
  }
}
```

Both live SSE events and replayed event lists run through the same reducer —
live view and history replay are the same code path at different speeds.
On page entry mid-run, the client first loads `/api/runs/{current_run_id}`
to catch up, then continues from SSE (no gap, duplicates de-duped by event
order index).

### Skin contract

```ts
interface Skin {
  id: string;                    // "atelier" | "ledger" | later: "kitchen"...
  label: string;
  mount(el: HTMLElement, callbacks: {onSelectWorker(flow: string)}): SkinHandle;
}
interface SkinHandle {
  update(stage: StageState): void;   // called on every stage change
  destroy(): void;
}
```

Skins render the stage; they never touch the API or interpret raw events.
Adding a kitchen/office/transit skin later = one new module implementing
this interface, registered in a skin list. Selection persists in
localStorage. The detail drawer (opened via `onSelectWorker`) is shared
React UI outside the skin.

### v1 skins

- **`atelier`** (default): an isometric workshop drawn with PixiJS from
  simple shapes (no sprite packs). One workbench per flow, an artisan
  figure that: sits idle when waiting (lamp dimmed), works at the bench
  while a node runs, reaches to a wall of tools on tool calls (the tool
  name appears briefly), shows a thought bubble on turns with thinking
  (click → drawer), stamps and shelves a finished piece on run completion,
  shows a red warning lamp on failure. Quiet ambient motion; respects
  prefers-reduced-motion by switching to state changes without tweens.
- **`ledger`**: the no-frills DOM view — flow cards with live status dot,
  current node, and a scrolling turn/tool feed. Proves the contract and
  serves anyone who wants density over charm.

## Failure handling

- SSE drop → EventSource auto-reconnects; client re-syncs via
  `/api/runs/{current_run_id}` before resuming.
- Malformed/unknown event types → reducer ignores them (forward compat).
- Store files missing (fresh daemon) → empty board with an invitation, not
  an error.

## Testing

- `BroadcastStore`: subscribe/publish, slow-subscriber eviction, zero-sub
  no-op (pytest, existing patterns).
- `node_turn` + thinking capture: mock-provider agent runs assert the event
  stream (test_runtime patterns); provider meta capture via the existing
  mocked `_post` / fake-stream tests.
- API: Starlette `TestClient` — flows listing, run replay, SSE first-frames.
- Frontend: vitest for the StageState reducer (event fixtures in, stage
  snapshots out) and the skin registry; skins themselves are verified
  manually in the browser against a mock-binding daemon.

## Implementation split

Two plans off this one spec:

- **Plan A — observation backend**: BroadcastStore, node_turn, thinking
  capture, FlowRunner status, server + API + SSE, CLI flags. Verifiable
  with curl alone.
- **Plan B — frontend**: Vite scaffold, StageState, ledger skin, atelier
  skin, skin picker, detail drawer, static serving wiring.
