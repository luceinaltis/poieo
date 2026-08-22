import { expect, test, vi } from "vitest"

import { createStageStore } from "./stageStore"
import type { StageApi } from "./stageStore"
import { AGENT_RUN } from "../state/fixtures"
import type { FeedHandlers } from "../api"
import type { FlowRow, PoieoEvent } from "../types"

const CHORES: FlowRow = {
  name: "chores",
  graph: "agent-task",
  trigger: "loop",
  status: "waiting",
  current_run_id: null,
  last_run: null,
  pending: 0,
}

function harness(overrides: Partial<StageApi> = {}) {
  let handlers: FeedHandlers | null = null
  const api: StageApi = {
    fetchFlows: vi.fn(async () => [CHORES]),
    fetchRunEvents: vi.fn(async () => [] as PoieoEvent[]),
    fetchRuns: vi.fn(async () => []),
    openFeed: vi.fn((h: FeedHandlers) => {
      handlers = h
      return () => {
        handlers = null
      }
    }),
    ...overrides,
  }
  return { api, store: createStageStore(api), feed: () => handlers! }
}

test("seeds from the flow list, then subscribes", async () => {
  const { api, store } = harness()
  await store.start()

  expect(api.fetchFlows).toHaveBeenCalled()
  expect(api.openFeed).toHaveBeenCalled()
  expect(Object.keys(store.getStage().workers)).toEqual(["chores"])
  store.stop()
})

test("no flows leaves an empty board, not an error", async () => {
  const { store } = harness({ fetchFlows: vi.fn(async () => []) })
  await store.start()

  expect(store.getStage().workers).toEqual({})
  store.stop()
})

test("live events fold into the stage", async () => {
  const { store, feed } = harness()
  await store.start()

  for (const event of AGENT_RUN.slice(0, 4)) feed().onEvent(event)
  expect(store.getStage().workers.chores.status).toBe("running")
  expect(store.getStage().workers.chores.currentNode).toBe("work")
  store.stop()
})

test("a resync applies the run's history before the live frames that overlapped it", async () => {
  // The hazard: history is older than the frames arriving while we read it.
  // Fold it in last and the board walks backwards; drop the live frames and
  // they are lost, because the run they belong to is not known yet.
  const history = AGENT_RUN.slice(0, 4) // in flight: run_started .. node_turn
  const live = AGENT_RUN.at(-1)! // run_finished, which lands mid-fetch

  let releaseHistory: (events: PoieoEvent[]) => void = () => {}
  const pending = new Promise<PoieoEvent[]>((resolve) => {
    releaseHistory = resolve
  })

  const { store, feed } = harness({
    fetchFlows: vi.fn(async () => [{ ...CHORES, current_run_id: AGENT_RUN[0].run_id }]),
    fetchRunEvents: vi.fn(() => pending),
  })
  await store.start()

  const resynced = store.resync()
  feed().onEvent(live) // arrives while the history fetch is still open
  releaseHistory(history)
  await resynced

  expect(store.getStage().workers.chores.status).toBe("waiting")
  expect(store.getStage().workers.chores.currentNode).toBeNull()
  store.stop()
})

test("a resync refreshes what finished while the feed was down", async () => {
  const summary = {
    run_id: "r-old",
    flow: "chores",
    graph: "agent-task",
    status: "completed",
    started_at: "2026-08-22T07:00:00+00:00",
    finished_at: "2026-08-22T07:00:01+00:00",
    steps: 4,
    iteration: 1,
    usage: {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
    },
    error: null,
  }
  const { store } = harness({
    fetchFlows: vi.fn(async () => [{ ...CHORES, last_run: summary }]),
  })
  await store.start()
  await store.resync()

  // The run_summary frame for that run was missed; /api/flows still knows.
  expect(store.getStage().workers.chores.lastRun).toEqual({
    status: "completed",
    steps: 4,
    finished_at: "2026-08-22T07:00:01+00:00",
  })
  store.stop()
})

test("subscribers hear about changes and stop when they unsubscribe", async () => {
  const { store, feed } = harness()
  await store.start()

  let beats = 0
  const off = store.subscribe(() => {
    beats += 1
  })
  feed().onEvent(AGENT_RUN[0])
  expect(beats).toBe(1)

  off()
  feed().onEvent(AGENT_RUN[1])
  expect(beats).toBe(1)
  store.stop()
})

test("stop closes the feed", async () => {
  const { store, feed } = harness()
  await store.start()
  expect(feed()).not.toBeNull()

  store.stop()
  expect(feed()).toBeNull()
})

test("feed status is reported through", async () => {
  const { store, feed } = harness()
  await store.start()

  feed().onStatus("lost")
  expect(store.getStatus()).toBe("lost")
  store.stop()
})


test("the store tallies each flow's recent work from the run index", async () => {
  const runs = [
    {
      run_id: "a",
      flow: "chores",
      graph: "agent-task",
      status: "completed",
      started_at: "t",
      finished_at: "t",
      steps: 1,
      iteration: 1,
      usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
      error: null,
      change: {
        base: "a",
        head: "b",
        files: ["one.py"],
        insertions: 9,
        deletions: 1,
        message: "did a thing",
      },
    },
  ]
  const { store } = harness({ fetchRuns: vi.fn(async () => runs) })

  await store.start()

  // The event stream never carries this: a browser opened at noon has to be
  // told what happened at 3am.
  expect(store.getStage().workers.chores.recent).toMatchObject({
    works: 1,
    succeeded: 1,
    insertions: 9,
  })
  store.stop()
})
