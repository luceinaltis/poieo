# Observation Backend Implementation Plan (Plan A)

**Goal:** A read-only HTTP + SSE surface inside `poieo daemon` that streams run events live and serves run history — verifiable with curl alone.

**Architecture:** A `BroadcastStore` wraps the daemon's `RunStore` so every stored event also lands on live subscriber queues. `AgentNode` emits a new turn-level event; providers capture separated "thinking" into response meta. A Starlette app on the daemon's own asyncio loop exposes flows/runs/events; uvicorn serves it on 127.0.0.1.

**Tech Stack:** Python 3.10, Starlette, uvicorn, pytest + pytest-asyncio (asyncio_mode=auto).

**Spec:** docs/specs/2026-08-22-web-observation-design.md

## Global Constraints

- New pip dependencies: exactly `starlette>=0.37` and `uvicorn>=0.29`, added to `[project.dependencies]`. Nothing else.
- Server binds `127.0.0.1` only; no `--host` option exists.
- Default port 8484; `--port N` overrides; `--no-web` disables.
- Everything is read-only: no route mutates anything.
- The daemon must never block on a slow browser: subscriber queues cap at 1000 (default), full queue ⇒ evict that subscriber.
- Test command on this machine (broken global pytest plugin): `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio`. Full suite currently passes 155 (+ 1 known-flaky `test_daemon.py` interval-timing test on Windows — rerun if it alone fails).
- Commit messages end with the trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Comment style: sparse, like existing modules — explain constraints, not mechanics.

---

### Task 1: BroadcastStore

**Files:**
- Create: `src/poieo/web/__init__.py`
- Create: `src/poieo/web/events.py`
- Test: `tests/test_web_events.py`

**Interfaces:**
- Consumes: `poieo.store.Event`, `poieo.store.RunStore` (`append(event)`, `record_summary(dict)`, `.root`).
- Produces: `BroadcastStore(inner: RunStore, queue_limit: int = 1000)` with `.subscribe() -> asyncio.Queue`, `.unsubscribe(queue)`, `.run_flows: dict[str, str]`; `append`/`record_summary` write through to `inner` AND publish dicts to subscribers. `run_summary` publishes as `{"type": "run_summary", **summary}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_events.py
"""BroadcastStore: events go to the file store and to live subscribers."""

import asyncio

from poieo.store import Event, RunStore
from poieo.web.events import BroadcastStore


def make_store(tmp_path):
    return BroadcastStore(RunStore(tmp_path / ".poieo"))


async def test_events_write_through_and_broadcast(tmp_path):
    store = make_store(tmp_path)
    queue = store.subscribe()

    event = Event(run_id="r1", type="run_started", data={"flow": "triage"})
    store.append(event)

    record = queue.get_nowait()
    assert record["type"] == "run_started"
    assert record["run_id"] == "r1"
    # written through to the JSONL store too
    assert [e["type"] for e in store.events("r1")] == ["run_started"]
    # flow learned for SSE filtering
    assert store.run_flows["r1"] == "triage"


async def test_summary_broadcast_and_run_flow_cleanup(tmp_path):
    store = make_store(tmp_path)
    queue = store.subscribe()
    store.append(Event(run_id="r1", type="run_started", data={"flow": "triage"}))
    queue.get_nowait()

    store.record_summary({"run_id": "r1", "flow": "triage", "status": "completed"})
    record = queue.get_nowait()
    assert record["type"] == "run_summary"
    assert record["status"] == "completed"
    assert "r1" not in store.run_flows
    assert store.list_runs()[0]["run_id"] == "r1"


async def test_slow_subscriber_is_evicted_not_blocking(tmp_path):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"), queue_limit=2)
    slow = store.subscribe()
    fast = store.subscribe()

    for i in range(4):  # two more than the slow queue can hold
        store.append(Event(run_id="r1", type="node_started", data={"step": i}))
        fast.get_nowait()

    # the slow queue filled at 2 and was dropped; publishing never raised
    assert slow.qsize() == 2
    store.append(Event(run_id="r1", type="node_started", data={"step": 9}))
    assert slow.qsize() == 2          # no longer receiving
    assert fast.get_nowait()["data"]["step"] == 9


async def test_unsubscribe_stops_delivery(tmp_path):
    store = make_store(tmp_path)
    queue = store.subscribe()
    store.unsubscribe(queue)
    store.append(Event(run_id="r1", type="node_started"))
    assert queue.qsize() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_web_events.py -q -p asyncio`
Expected: FAIL with `ModuleNotFoundError: No module named 'poieo.web'`

- [ ] **Step 3: Implement**

```python
# src/poieo/web/__init__.py
"""The daemon's web face: event fan-out and the observation server."""

from .events import BroadcastStore

__all__ = ["BroadcastStore"]
```

```python
# src/poieo/web/events.py
"""Fan-out layer: every stored event is also pushed to live subscribers."""

from __future__ import annotations

import asyncio
from typing import Any

from ..store import Event, RunStore


class BroadcastStore(RunStore):
    """Wraps a RunStore: writes go through, and live subscribers see them too.

    Subscribers are asyncio queues on the daemon's loop. The store never
    waits on a subscriber: a full queue means the browser stopped reading,
    and that subscriber is evicted (EventSource reconnects on its own).
    """

    def __init__(self, inner: RunStore, queue_limit: int = 1000):
        super().__init__(inner.root)
        self._inner = inner
        self._queue_limit = queue_limit
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        # run_id -> flow, learned from run_started, so the SSE endpoint can
        # filter by flow without parsing every payload.
        self.run_flows: dict[str, str] = {}

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_limit)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def _publish(self, record: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                self._subscribers.discard(queue)

    def append(self, event: Event) -> None:
        self._inner.append(event)
        if event.type == "run_started":
            flow = event.data.get("flow")
            if flow:
                self.run_flows[event.run_id] = flow
        self._publish(event.as_dict())

    def record_summary(self, summary: dict[str, Any]) -> None:
        self._inner.record_summary(summary)
        self.run_flows.pop(summary.get("run_id"), None)
        self._publish({"type": "run_summary", **summary})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_web_events.py -q -p asyncio`
Expected: 4 passed. Then the full suite: 159 passed.

- [ ] **Step 5: Commit**

```bash
git add src/poieo/web tests/test_web_events.py
git commit -m "feat: BroadcastStore fans stored events out to live subscribers"
```

---

### Task 2: node_turn event

**Files:**
- Modify: `src/poieo/runtime/nodes.py` (AgentNode.run, inside the while loop)
- Test: `tests/test_runtime.py` (append)

**Interfaces:**
- Consumes: `ctx.emit(type, node_id=..., **data)`, `_clip(value)` (already in nodes.py), `response.meta` (dict).
- Produces: one `node_turn` event per completed model turn: `data = {turn, text, thinking, tool_call_count}`. Emitted for EVERY turn including the final no-tool-calls turn.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runtime.py`. It already has `mock_binding(responses)`, `run_graph(graph, binding, **kwargs)`, `GraphSpec`, and a `RecordingStore`-style pattern — reuse the store the file already uses for event assertions (look at how existing tests capture events; they pass a store into `run_graph` via `store=`). If no capturing store exists, use this one:

```python
class _CapturingStore(NullStore):
    def __init__(self):
        super().__init__()
        self.events = []

    def append(self, event):
        self.events.append(event)


async def test_agent_node_emits_a_turn_event_per_model_turn(tmp_path):
    graph = GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "work",
            "nodes": [
                {
                    "id": "work",
                    "type": "agent",
                    "role": "worker",
                    "workdir": str(tmp_path),
                    "prompt": "go",
                }
            ],
        }
    )
    binding = mock_binding(
        {
            "worker": [
                {
                    "text": "looking",
                    "thinking": "let me see",
                    "tool_calls": [{"name": "list_dir", "arguments": {}}],
                },
                "all done",
            ]
        }
    )
    store = _CapturingStore()
    result = await run_graph(graph, binding, store=store)

    assert result.status == "completed"
    turns = [e for e in store.events if e.type == "node_turn"]
    assert [t.data["turn"] for t in turns] == [1, 2]
    assert turns[0].data["tool_call_count"] == 1
    assert turns[0].data["thinking"] == "let me see"
    assert turns[1].data["text"] == "all done"
    assert turns[1].data["tool_call_count"] == 0
```

Note: `"thinking"` in a mock script entry does not reach `meta` until Task 3 — but this test must pass at the END of Task 2. So Task 2 also adds the mock-provider side (one line, see Step 3). If `run_graph` has no `store=` parameter, extend the helper minimally to accept and pass it through to `execute`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime.py -q -p asyncio -k turn_event`
Expected: FAIL (no node_turn events found).

- [ ] **Step 3: Implement**

In `src/poieo/runtime/nodes.py`, `AgentNode.run`, directly after `ctx.usage = ctx.usage.merge(response.usage)`:

```python
            ctx.emit(
                "node_turn",
                node_id=spec.id,
                turn=turns,
                text=_clip(response.text),
                thinking=_clip(response.meta.get("thinking") or ""),
                tool_call_count=len(response.tool_calls),
            )
```

In `src/poieo/providers/mock.py`, where dict script entries are unpacked (the branch that reads `value.get("tool_calls")`), also carry thinking into the response meta so scripted runs can exercise it:

```python
        meta: dict[str, Any] = {}
        if isinstance(value, dict) and value.get("thinking"):
            meta["thinking"] = value["thinking"]
```

(merge with the existing `meta` handling added for `raw_content` — one dict, both keys.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime.py -q -p asyncio`
Expected: all pass. Then full suite.

- [ ] **Step 5: Commit**

```bash
git add src/poieo/runtime/nodes.py src/poieo/providers/mock.py tests/test_runtime.py
git commit -m "feat: agent nodes emit a node_turn event per model turn"
```

---

### Task 3: thinking capture in ollama and anthropic providers

**Files:**
- Modify: `src/poieo/providers/local.py` (OllamaProvider.complete)
- Modify: `src/poieo/providers/anthropic_provider.py` (complete)
- Test: `tests/test_providers.py` (append)

**Interfaces:**
- Consumes: existing `complete()` bodies; `LLMResponse.meta`.
- Produces: `LLMResponse.meta["thinking"]` set when the backend separates reasoning — Ollama from `message["thinking"]`, anthropic by joining `thinking` blocks from `message.content`. Absent key when there is none.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_providers.py` (it already has monkeypatched `_post` ollama tests and the fake-stream anthropic pattern with `_block`/`_message` helpers from the raw_content work — follow those exactly):

```python
async def test_ollama_captures_separated_thinking(monkeypatch):
    spec = ProviderSpec.model_validate({"type": "ollama", "base_url": "http://x"})
    provider = OllamaProvider("ollama", spec)

    async def fake_post(path, payload):
        return {
            "model": "m",
            "message": {"content": "answer", "thinking": "hmm, tricky"},
            "done_reason": "stop",
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    response = await provider.complete(
        LLMRequest(model="m", messages=[{"role": "user", "content": "q"}])
    )
    assert response.meta["thinking"] == "hmm, tricky"
    await provider.aclose()


async def test_anthropic_captures_thinking_blocks(monkeypatch):
    # reuse the fake-stream pattern: a message whose content holds a thinking
    # block and a text block (same _block/_message helpers as the raw_content
    # tests in this file).
    message = _message(
        content=[
            _block("thinking", thinking="step one, step two"),
            _block("text", text="final answer"),
        ]
    )
    provider = _provider_with_stream(monkeypatch, message)
    response = await provider.complete(
        LLMRequest(model="claude-opus-5", messages=[{"role": "user", "content": "q"}])
    )
    assert response.meta["thinking"] == "step one, step two"
    assert response.text == "final answer"
```

Adapt helper names to what the file actually defines (`_block`, `_message`, and how the raw_content tests build a provider with a fake stream — read them first and mirror; if there is no `_provider_with_stream` helper, inline the same monkeypatching those tests use).

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_providers.py -q -p asyncio -k thinking`
Expected: FAIL with KeyError 'thinking'.

- [ ] **Step 3: Implement**

`local.py`, in `OllamaProvider.complete` where the response message is unpacked:

```python
        meta: dict[str, Any] = {}
        if message.get("thinking"):
            meta["thinking"] = message["thinking"]
```

and pass `meta=meta` to the `LLMResponse`.

`anthropic_provider.py`, in `complete()` next to the existing text extraction:

```python
        thinking = "\n".join(
            getattr(b, "thinking", "") for b in message.content if b.type == "thinking"
        )
```

and add to the existing meta dict: `**({"thinking": thinking} if thinking else {})` (keep `message_id` and `raw_content` as they are).

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_providers.py -q -p asyncio`
Expected: all pass. Then full suite.

- [ ] **Step 5: Commit**

```bash
git add src/poieo/providers/local.py src/poieo/providers/anthropic_provider.py tests/test_providers.py
git commit -m "feat: providers capture separated thinking into response meta"
```

---

### Task 4: FlowRunner live status

**Files:**
- Modify: `src/poieo/daemon/service.py` (FlowRunner)
- Test: `tests/test_daemon.py` (append)

**Interfaces:**
- Consumes: `FlowRunner.run()` loop; `execute(..., run_id=...)`; `new_run_id()` from `poieo.runtime.context`.
- Produces: `runner.status` ("waiting" | "running"), `runner.current_run_id` (str | None), `runner.last_result` (RunResult | None property over `self.results`). The API (Task 5) reads exactly these three names.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_daemon.py` (mirror how existing tests build a daemon config with the mock binding and run `--once`-style; the file has helpers for temp configs — reuse them):

```python
async def test_flow_runner_exposes_live_status(tmp_path, daemon_config_factory):
    # Use the existing test fixtures/helpers in this file to build a one-shot
    # daemon (loop trigger, max_iterations=1, mock binding). After serve():
    daemon = build_once_daemon(daemon_config_factory)   # per this file's pattern
    results = await daemon.serve(install_signals=False)

    runner = daemon.runners[0]
    assert runner.status == "waiting"           # back to waiting after the run
    assert runner.current_run_id is None
    assert runner.last_result is results[-1]
    assert runner.last_result.status == "completed"
```

The exact fixture names differ — the implementer reads `tests/test_daemon.py` first and uses its existing construction pattern (there are already tests that run a daemon to completion with mock bindings). The assertions above are the contract; only the setup lines adapt.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_daemon.py -q -p asyncio -k live_status`
Expected: FAIL with AttributeError: 'FlowRunner' object has no attribute 'status'.

- [ ] **Step 3: Implement**

In `FlowRunner.__init__` add:

```python
        self.status: str = "waiting"
        self.current_run_id: str | None = None
```

Add a property:

```python
    @property
    def last_result(self) -> RunResult | None:
        return self.results[-1] if self.results else None
```

In `FlowRunner.run()`, wrap the execute call (import `new_run_id` from `..runtime.context`):

```python
            run_id = new_run_id()
            self.status, self.current_run_id = "running", run_id
            try:
                result = await execute(
                    ...existing args...,
                    run_id=run_id,
                )
            finally:
                self.status, self.current_run_id = "waiting", None
```

(keep every existing argument to `execute` unchanged; only `run_id=` is new.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_daemon.py -q -p asyncio`
Expected: all pass (rerun once if only the known-flaky interval test fails). Then full suite.

- [ ] **Step 5: Commit**

```bash
git add src/poieo/daemon/service.py tests/test_daemon.py
git commit -m "feat: flow runners expose live status for the web API"
```

---

### Task 5: Starlette app — flows, runs, SSE

**Files:**
- Create: `src/poieo/web/server.py`
- Modify: `pyproject.toml` (add `starlette>=0.37`, `uvicorn>=0.29` to `[project.dependencies]`)
- Modify: `src/poieo/web/__init__.py` (export `create_app`)
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: an object with `.runners` (each: `name`, `status`, `current_run_id`, `last_result`, `trigger.describe`, `flow.graph.name`) and `.store` (a `BroadcastStore`). The real Daemon satisfies this after Task 6; tests use a stub.
- Produces: `create_app(daemon) -> Starlette` with routes exactly: `GET /api/flows`, `GET /api/runs`, `GET /api/runs/{run_id}`, `GET /api/events` (SSE), `GET /` (static or fallback). Also `_event_stream(store, flow)` async generator (unit-testable) and `sse_frame(record) -> str`.

- [ ] **Step 1: Install the dependencies and add them to pyproject**

```bash
python -m pip install "starlette>=0.37" "uvicorn>=0.29" httpx
```

In `pyproject.toml` `[project] dependencies`, append `"starlette>=0.37",` and `"uvicorn>=0.29",`. (httpx is already a dependency; Starlette's TestClient needs it at test time only.)

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_web_server.py
"""The observation API over a stub daemon."""

import asyncio
from types import SimpleNamespace

from starlette.testclient import TestClient

from poieo.store import Event, RunStore
from poieo.web.events import BroadcastStore
from poieo.web.server import create_app, sse_frame, _event_stream


def stub_daemon(tmp_path, runners=()):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    return SimpleNamespace(runners=list(runners), store=store)


def stub_runner(name="triage", status="waiting", current=None, last=None):
    return SimpleNamespace(
        name=name,
        status=status,
        current_run_id=current,
        last_result=last,
        trigger=SimpleNamespace(describe=f"interval 30s"),
        flow=SimpleNamespace(graph=SimpleNamespace(name="support-triage")),
    )


def test_flows_lists_runner_state(tmp_path):
    last = SimpleNamespace(summary=lambda: {"run_id": "r0", "status": "completed"})
    daemon = stub_daemon(tmp_path, [stub_runner(last=last)])
    client = TestClient(create_app(daemon))

    body = client.get("/api/flows").json()
    assert body["flows"] == [
        {
            "name": "triage",
            "graph": "support-triage",
            "trigger": "interval 30s",
            "status": "waiting",
            "current_run_id": None,
            "last_run": {"run_id": "r0", "status": "completed"},
        }
    ]


def test_runs_index_and_detail_and_404(tmp_path):
    daemon = stub_daemon(tmp_path)
    daemon.store.append(Event(run_id="r1", type="run_started", data={"flow": "t"}))
    daemon.store.record_summary({"run_id": "r1", "flow": "t", "status": "completed"})
    client = TestClient(create_app(daemon))

    runs = client.get("/api/runs").json()["runs"]
    assert runs[0]["run_id"] == "r1"
    detail = client.get("/api/runs/r1").json()
    assert detail["run_id"] == "r1"
    assert detail["events"][0]["type"] == "run_started"
    assert client.get("/api/runs/nope").status_code == 404


def test_root_serves_fallback_without_built_ui(tmp_path):
    client = TestClient(create_app(stub_daemon(tmp_path)))
    response = client.get("/")
    assert response.status_code == 200
    assert "/api/flows" in response.text


def test_sse_frame_format():
    assert sse_frame({"type": "x"}) == 'data: {"type": "x"}\n\n'


async def test_event_stream_yields_and_filters(tmp_path):
    store = BroadcastStore(RunStore(tmp_path / ".poieo"))
    stream = _event_stream(store, flow="triage")

    async def first_frame():
        return await stream.__anext__()

    task = asyncio.create_task(first_frame())
    await asyncio.sleep(0)  # let the generator subscribe
    # an event for another flow is filtered out, ours comes through
    store.append(Event(run_id="a", type="run_started", data={"flow": "other"}))
    store.append(Event(run_id="b", type="run_started", data={"flow": "triage"}))
    frame = await asyncio.wait_for(task, timeout=2)
    assert '"run_id": "b"' in frame
    await stream.aclose()


def test_events_endpoint_handshake(tmp_path):
    client = TestClient(create_app(stub_daemon(tmp_path)))
    with client.stream("GET", "/api/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_web_server.py -q -p asyncio`
Expected: FAIL with ImportError (no poieo.web.server).

- [ ] **Step 4: Implement**

```python
# src/poieo/web/server.py
"""Read-only observation API served from inside the daemon.

Everything here answers "what is happening / what happened" -- no route
mutates anything. Control endpoints belong to the next roadmap slice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .events import BroadcastStore

STATIC_DIR = Path(__file__).parent / "static"


def sse_frame(record: dict[str, Any]) -> str:
    return f"data: {json.dumps(record, ensure_ascii=False)}\n\n"


async def _event_stream(store: BroadcastStore, flow: str | None) -> AsyncIterator[str]:
    queue = store.subscribe()
    try:
        while True:
            record = await queue.get()
            if flow:
                run_flow = record.get("flow") or store.run_flows.get(record.get("run_id", ""))
                if run_flow != flow:
                    continue
            yield sse_frame(record)
    finally:
        store.unsubscribe(queue)


def create_app(daemon: Any) -> Starlette:
    """Build the app over a daemon-shaped object (.runners, .store)."""

    def flows(request: Request) -> JSONResponse:
        rows = []
        for runner in daemon.runners:
            last = runner.last_result
            rows.append(
                {
                    "name": runner.name,
                    "graph": runner.flow.graph.name,
                    "trigger": runner.trigger.describe,
                    "status": runner.status,
                    "current_run_id": runner.current_run_id,
                    "last_run": last.summary() if last else None,
                }
            )
        return JSONResponse({"flows": rows})

    def runs(request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", "20"))
        flow = request.query_params.get("flow")
        return JSONResponse({"runs": daemon.store.list_runs(limit=limit, flow=flow)})

    def run_detail(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        events = list(daemon.store.events(run_id))
        if not events:
            return JSONResponse({"error": f"no run '{run_id}'"}, status_code=404)
        return JSONResponse({"run_id": run_id, "events": events})

    async def events(request: Request) -> StreamingResponse:
        flow = request.query_params.get("flow")
        return StreamingResponse(
            _event_stream(daemon.store, flow),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"},
        )

    def index(request: Request):
        page = STATIC_DIR / "index.html"
        if page.exists():
            return FileResponse(page)
        return PlainTextResponse(
            "poieo web UI is not built yet. The API is live: /api/flows"
        )

    routes = [
        Route("/api/flows", flows),
        Route("/api/runs", runs),
        Route("/api/runs/{run_id}", run_detail),
        Route("/api/events", events),
        Route("/", index),
    ]
    if STATIC_DIR.is_dir():
        routes.append(Mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets"))
    return Starlette(routes=routes)
```

Update `src/poieo/web/__init__.py`:

```python
from .events import BroadcastStore
from .server import create_app

__all__ = ["BroadcastStore", "create_app"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_web_server.py -q -p asyncio`
Expected: 7 passed. Then full suite.

- [ ] **Step 6: Commit**

```bash
git add src/poieo/web pyproject.toml tests/test_web_server.py
git commit -m "feat: observation API - flows, run history, SSE stream"
```

---

### Task 6: daemon integration and CLI flags

**Files:**
- Modify: `src/poieo/daemon/service.py` (Daemon)
- Modify: `src/poieo/cli.py` (daemon command)
- Test: `tests/test_daemon.py` (append)

**Interfaces:**
- Consumes: Task 5's `create_app`; Task 1's `BroadcastStore`; uvicorn.
- Produces: `Daemon(config, *, store=None, on_run=None, web_port: int | None = None)`. When `web_port` is set: store is wrapped in BroadcastStore (unless it already is one), `_ensure_port_free("127.0.0.1", port)` raises `SpecError` if taken, uvicorn serves `create_app(self)` on the daemon loop, and shutdown stops it. CLI: `poieo daemon CONFIG --port 8484` (default) / `--no-web`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_daemon.py`:

```python
import socket

from poieo.daemon.service import _ensure_port_free
from poieo.errors import SpecError
from poieo.web.events import BroadcastStore


def test_ensure_port_free_raises_when_taken():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        with pytest.raises(SpecError, match=str(port)):
            _ensure_port_free("127.0.0.1", port)


def test_ensure_port_free_passes_on_free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    _ensure_port_free("127.0.0.1", port)  # released above; must not raise


async def test_daemon_with_web_port_wraps_store_and_serves(tmp_path, ...):
    # build a one-shot daemon per this file's existing pattern, plus:
    daemon = build_once_daemon(..., web_port=free_port())
    serve_task = asyncio.create_task(daemon.serve(install_signals=False))
    # while it runs, the API answers:
    #   poll http://127.0.0.1:{port}/api/flows with httpx.AsyncClient until 200
    #   assert the flow name appears
    results = await asyncio.wait_for(serve_task, timeout=30)
    assert isinstance(daemon.store, BroadcastStore)
    assert results  # the one-shot run finished and the server shut down cleanly
```

The third test's setup follows the file's existing daemon-construction helpers; `free_port()` = bind-then-release as above. Poll with `httpx.AsyncClient` (already a dependency), 0.1s interval, 5s cap.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_daemon.py -q -p asyncio -k "port_free or web_port"`
Expected: ImportError (`_ensure_port_free` does not exist).

- [ ] **Step 3: Implement**

In `src/poieo/daemon/service.py`:

```python
import socket

from ..errors import PoieoError, SpecError
from ..web import BroadcastStore, create_app


def _ensure_port_free(host: str, port: int) -> None:
    """Fail at launch, not after flows have started."""
    with socket.socket() as sock:
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise SpecError(
                f"web port {port} is already in use on {host}: {exc}"
            ) from exc
```

`Daemon.__init__` gains `web_port: int | None = None`; store the value; wrap the store:

```python
        base_store = store or RunStore(config.store_path())
        if web_port is not None and not isinstance(base_store, BroadcastStore):
            base_store = BroadcastStore(base_store)
        self.store = base_store
        self.web_port = web_port
```

In `Daemon.serve()`, after `_install_signals()` and before building runners:

```python
        web_task = None
        if self.web_port is not None:
            import uvicorn

            _ensure_port_free("127.0.0.1", self.web_port)
            server = uvicorn.Server(
                uvicorn.Config(
                    create_app(self),
                    host="127.0.0.1",
                    port=self.web_port,
                    log_level="warning",
                )
            )
            web_task = asyncio.create_task(server.serve())
            log.info("web observation UI on http://127.0.0.1:%d", self.web_port)
```

and in the existing `finally` block, before closing pools:

```python
            if web_task is not None:
                server.should_exit = True
                try:
                    await asyncio.wait_for(web_task, timeout=5)
                except (asyncio.TimeoutError, Exception):
                    web_task.cancel()
```

NOTE: uvicorn installs its own signal handlers by default when serving —
that would fight the daemon's. `uvicorn.Server.serve()` skips signal
installation when not on the main thread, but here we ARE on the main
thread: pass `uvicorn.Config(..., )` and override by setting
`server.install_signal_handlers = lambda: None` right after constructing
the Server. Include exactly that line.

In `src/poieo/cli.py` `daemon` command, add options and pass through:

```python
    port: int = typer.Option(8484, "--port", help="Web observation UI port."),
    no_web: bool = typer.Option(False, "--no-web", help="Disable the web UI."),
```

```python
        results = asyncio.run(
            Daemon(config, web_port=None if no_web else port).serve()
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_daemon.py -q -p asyncio`
Expected: all pass (rerun once if only the known-flaky interval test fails). Then full suite.

- [ ] **Step 5: Manual smoke test**

```bash
python main.py daemon examples/poieo.yaml --once --flow triage &
sleep 2
curl -s http://127.0.0.1:8484/api/flows
curl -s -N --max-time 3 http://127.0.0.1:8484/api/events | head -5
```

Expected: flows JSON with "triage"; SSE frames scroll as the mock flow runs. Paste the output into the report.

- [ ] **Step 6: Commit**

```bash
git add src/poieo/daemon/service.py src/poieo/cli.py tests/test_daemon.py
git commit -m "feat: daemon serves the observation API on 127.0.0.1"
```

---

### Task 7: demo thinking in the mock example and README

**Files:**
- Modify: `examples/bindings/mock.yaml` (worker script: add a `thinking` line to the first entry)
- Modify: `README.md` (daemon section: two short paragraphs — the web UI URL/flags, and that `/api/events` streams run events live; match the README's plain tone)
- Test: existing suite only (the example file is loaded by `test_runtime`'s example test — it must still pass)

**Interfaces:**
- Consumes: mock dict-script support for `thinking` (Task 2).
- Produces: documentation and a demo that shows a thought bubble in Plan B.

- [ ] **Step 1: Edit the example**

In `examples/bindings/mock.yaml`, find the `worker` script's first entry (the one with the `list_dir` tool call) and add a sibling key:

```yaml
        thinking: "First see what is in this directory."
```

- [ ] **Step 2: Update README.md**

In the daemon ("resident layer") section, after the existing `poieo daemon` examples, add:

```markdown
While the daemon runs it serves a read-only observation page on
`http://127.0.0.1:8484` (`--port` to change it, `--no-web` to turn it off).
`GET /api/events` streams every run event live (SSE); `/api/flows` and
`/api/runs` answer what is running and what already ran.
```

- [ ] **Step 3: Run the full suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p asyncio`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add examples/bindings/mock.yaml README.md
git commit -m "docs: observation API in README; mock demo shows thinking"
```
