import { beforeEach, expect, test, vi } from "vitest"

import { fetchFlows, fetchRunEvents, fetchRuns, openFeed } from "./api"
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
  const fetchStub = vi.fn(async (path: string) => {
    const hit = routes[path]
    const status = hit ? (hit.status ?? 200) : 404
    return {
      ok: status < 400,
      status,
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

test("fetchFlows unwraps the envelope", async () => {
  stubFetch({ "/api/flows": { body: { flows: [{ name: "triage" }] } } })
  expect(await fetchFlows()).toEqual([{ name: "triage" }])
})

test("fetchRuns passes flow and limit through as query params", async () => {
  const fetchStub = stubFetch({ "/api/runs?flow=triage&limit=5": { body: { runs: [] } } })
  await fetchRuns({ flow: "triage", limit: 5 })
  expect(fetchStub).toHaveBeenCalledWith("/api/runs?flow=triage&limit=5")
})

test("fetchRunEvents returns [] for a 404 run", async () => {
  stubFetch({})
  // A fresh daemon has no runs at all -- that is an empty board, not an error.
  await expect(fetchRunEvents("nope")).resolves.toEqual([])
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
