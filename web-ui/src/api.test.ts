import { beforeEach, expect, test, vi } from "vitest"

import {
  askMemory,
  fetchMemory,
  fetchRunEvents,
  fetchRuns,
  fetchTasks,
  openFeed,
  pause,
  resume,
  runNow,
  searchMemory,
} from "./api"
import type { PoieoEvent } from "./types"

class FakeEventSource {
  static instances: FakeEventSource[] = []

  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((message: { data: string }) => void) | null = null
  closed = false

  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }

  // -- driving the fake from a test
  open() {
    this.onopen?.()
  }
  drop() {
    this.onerror?.()
  }
  deliver(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
  deliverRaw(data: string) {
    this.onmessage?.({ data })
  }
}

function stubFetch(routes: Record<string, { status?: number; body: unknown }>) {
  const fetchStub = vi.fn(async (path: string, _init?: RequestInit) => {
    const hit = routes[path]
    const status = hit ? (hit.status ?? 200) : 404
    return {
      ok: status < 400,
      status,
      headers: { get: () => null },
      json: async () => (hit ? hit.body : { error: "no such thing" }),
    }
  })
  vi.stubGlobal("fetch", fetchStub)
  return fetchStub
}

function collect() {
  const events: PoieoEvent[] = []
  const statuses: string[] = []
  let resyncs = 0
  const handlers = {
    onEvent: (event: PoieoEvent) => events.push(event),
    onStatus: (status: string) => statuses.push(status),
    onResync: () => {
      resyncs += 1
    },
  }
  return { events, statuses, handlers, resyncs: () => resyncs }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal("EventSource", FakeEventSource)
})

test("fetchTasks keeps the whole listing, project and all", async () => {
  // Not unwrapped to the tasks any more: the project rides on the listing,
  // and the listing with no tasks in it is the one that most needs a name.
  const projects = [{ name: "night shift", root: "/home/k/chores" }]
  stubFetch({ "/api/tasks": { body: { projects, tasks: [{ name: "triage" }] } } })
  expect(await fetchTasks()).toEqual({ projects, tasks: [{ name: "triage" }] })
})

test("a listing the daemon did not answer is an empty board, not a crash", async () => {
  stubFetch({})
  expect(await fetchTasks()).toEqual({ projects: [], tasks: [] })
})

test("memory reads the selected project and search posts its mode", async () => {
  const fetchStub = stubFetch({
    "/api/projects/night%20shift/memory": {
      body: {
        enabled: true,
        graph: {
          nodes: [],
          edges: [],
          total_nodes: 0,
          total_edges: 0,
          truncated: false,
          edges_truncated: false,
        },
      },
    },
    "/api/projects/night%20shift/memory/search": {
      body: { query: "셸", mode: "meaning", results: [] },
    },
  })

  expect((await fetchMemory("night shift"))?.enabled).toBe(true)
  expect(await searchMemory("night shift", "셸", "meaning", false)).toMatchObject({
    ok: true,
    mode: "meaning",
  })
  expect(fetchStub).toHaveBeenLastCalledWith(
    "/api/projects/night%20shift/memory/search",
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        query: "셸",
        mode: "meaning",
        limit: 20,
        include_set_aside: false,
      }),
    },
  )
})

test("memory revalidation accepts an unchanged overview without a body", async () => {
  const fetchStub = stubFetch({
    "/api/projects/board/memory": { status: 304, body: null },
  })

  expect(await fetchMemory("board", '"memory-one"')).toBeUndefined()
  expect(fetchStub).toHaveBeenCalledWith("/api/projects/board/memory", {
    cache: "no-store",
    headers: { "if-none-match": '"memory-one"' },
  })
})

test("asking memory sends a question rather than disguising it as search", async () => {
  const fetchStub = stubFetch({
    "/api/projects/board/memory/ask": {
      body: { answer: "because [[shell]]", citations: ["shell"], evidence: [] },
    },
  })

  expect(await askMemory("board", "why?", true)).toMatchObject({
    ok: true,
    citations: ["shell"],
  })
  expect(fetchStub).toHaveBeenCalledWith(
    "/api/projects/board/memory/ask",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ question: "why?", include_set_aside: true }),
    }),
  )
})

test("an older daemon that names no project still lists its tasks", async () => {
  stubFetch({ "/api/tasks": { body: { tasks: [{ name: "triage" }] } } })
  expect(await fetchTasks()).toEqual({ projects: [], tasks: [{ name: "triage" }] })
})

test("fetchRuns passes task and limit through as query params", async () => {
  const fetchStub = stubFetch({ "/api/runs?task=triage&limit=5": { body: { runs: [] } } })
  await fetchRuns({ task: "triage", limit: 5 })
  expect(fetchStub).toHaveBeenCalledWith("/api/runs?task=triage&limit=5")
})

test("fetchRunEvents returns [] for a 404 run", async () => {
  stubFetch({})
  // A fresh daemon has no runs at all -- that is an empty board, not an error.
  await expect(fetchRunEvents("nope")).resolves.toEqual([])
})

test("the control verbs post to their routes and unwrap the answer", async () => {
  const fetchStub = stubFetch({
    "/api/tasks/board/chores/pause": { body: { status: "paused" } },
    "/api/tasks/board/chores/resume": { body: { status: "waiting" } },
    "/api/tasks/board/chores/run": { body: { status: "starting" } },
  })

  expect(await pause("board", "chores")).toEqual({ ok: true, status: "paused" })
  expect(await resume("board", "chores")).toEqual({ ok: true, status: "waiting" })
  expect(await runNow("board", "chores")).toEqual({ ok: true, status: "starting" })
  for (const call of fetchStub.mock.calls) {
    expect(call[1]).toEqual({ method: "POST" })
  }
})

test("a refused run comes back as an answer, not a throw", async () => {
  stubFetch({
    "/api/tasks/board/chores/run": {
      status: 409,
      body: { error: "a run is in flight", run_id: "r7" },
    },
  })

  expect(await runNow("board", "chores")).toEqual({
    ok: false,
    error: "a run is in flight",
    run_id: "r7",
  })
})

test("openFeed parses frames and reports status", () => {
  const { events, statuses, handlers } = collect()
  openFeed(handlers)
  const source = FakeEventSource.instances[0]

  expect(statuses).toEqual(["connecting"])
  source.open()
  source.deliver({ run_id: "r1", type: "run_started", at: "t0" })
  source.drop()

  expect(statuses).toEqual(["connecting", "live", "lost"])
  expect(events).toEqual([{ run_id: "r1", type: "run_started", at: "t0" }])
})

test("a malformed frame is skipped, not thrown", () => {
  const { events, handlers } = collect()
  openFeed(handlers)
  const source = FakeEventSource.instances[0]

  expect(() => source.deliverRaw("{not json")).not.toThrow()
  source.deliver({ run_id: "r1", type: "run_started" })
  expect(events).toHaveLength(1)
})

test("openFeed calls onResync on every open, not just the first", () => {
  const { resyncs, handlers } = collect()
  openFeed(handlers)
  const source = FakeEventSource.instances[0]

  source.open()
  source.drop()
  source.open() // EventSource reconnected on its own; the gap still needs filling
  expect(resyncs()).toBe(2)
})

test("the close function detaches and stops delivery", () => {
  const { events, handlers } = collect()
  const close = openFeed(handlers)
  const source = FakeEventSource.instances[0]

  close()
  source.deliver({ run_id: "r1", type: "run_started" })

  expect(source.closed).toBe(true)
  expect(events).toEqual([])
})

test("a frame saying the listing changed asks for a resync, not a fold", () => {
  // Nothing is published when a card file changes under an open page, and the
  // board reads /api/tasks only when it opens. So the daemon says "ask again",
  // and this is the one frame that is not a run event: it carries no detail,
  // because the read is the detail and a second answer here would be free to
  // be the wrong one.
  const { events, resyncs, handlers } = collect()
  openFeed(handlers)
  const source = FakeEventSource.instances[0]

  source.open()
  source.deliver({ type: "tasks_changed", project: "board" })

  expect(resyncs()).toBe(2) // the open, then the frame
  expect(events).toEqual([]) // and nothing reached the reducer
})
