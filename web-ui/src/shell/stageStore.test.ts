import { expect, test, vi } from "vitest"

import { createStageStore } from "./stageStore"
import type { StageApi } from "./stageStore"
import { AGENT_RUN } from "../state/fixtures"
import type { FeedHandlers } from "../api"
import type { Listing, TaskRow, PoieoEvent, RunSummary } from "../types"

const CHORES: TaskRow = {
  name: "chores",
  project: "board",
  graph: "agent-task",
  trigger: "loop",
  status: "waiting",
  holding: false,
  enabled: true,
  stale: null,
  current_run_id: null,
  last_run: null,
  pending: 0,
  into: null,
  asking: null,
  then: [],
  shape: { entry: "", nodes: [] },
}

const CHANGED_RUN: RunSummary = {
  run_id: "changed-live",
  task: "chores",
  project: "board",
  graph: "agent-task",
  status: "completed",
  started_at: "2026-08-31T09:00:00Z",
  finished_at: "2026-08-31T09:00:05Z",
  steps: 1,
  iteration: 1,
  trigger: "loop",
  usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
  error: null,
  said: "updated the guide",
  change: {
    base: "a",
    head: "b",
    files: ["GUIDE.md"],
    insertions: 4,
    deletions: 0,
    message: "updated the guide",
  },
}

/** The envelope `/api/tasks` answers. Only the tasks matter to most of these,
 *  so the project is a constant rather than an argument. */
function listing(tasks: TaskRow[]): Listing {
  return { projects: [{ name: "board", root: "/home/k/chores", keeps_copies: true }], tasks }
}

function harness(overrides: Partial<StageApi> = {}) {
  let handlers: FeedHandlers | null = null
  const api: StageApi = {
    fetchTasks: vi.fn(async () => listing([CHORES])),
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

test("seeds from the task list, then subscribes", async () => {
  const { api, store } = harness()
  await store.start()

  expect(api.fetchTasks).toHaveBeenCalled()
  expect(api.openFeed).toHaveBeenCalled()
  expect(Object.keys(store.getStage().tasks)).toEqual(["board/chores"])
  store.stop()
})

test("no tasks leaves an empty board, not an error", async () => {
  const { store } = harness({ fetchTasks: vi.fn(async () => listing([])) })
  await store.start()

  expect(store.getStage().tasks).toEqual({})
  store.stop()
})

test("live events fold into the stage", async () => {
  const { store, feed } = harness()
  await store.start()

  for (const event of AGENT_RUN.slice(0, 4)) feed().onEvent(event)
  expect(store.getStage().tasks["board/chores"].status).toBe("running")
  expect(store.getStage().tasks["board/chores"].currentNode).toBe("work")
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
    fetchTasks: vi.fn(async () => listing([{ ...CHORES, current_run_id: AGENT_RUN[0].run_id }])),
    fetchRunEvents: vi.fn(() => pending),
  })
  await store.start()

  const resynced = store.resync()
  feed().onEvent(live) // arrives while the history fetch is still open
  releaseHistory(history)
  await resynced

  expect(store.getStage().tasks["board/chores"].status).toBe("waiting")
  expect(store.getStage().tasks["board/chores"].currentNode).toBeNull()
  store.stop()
})

test("a changed summary after the task listing still increments review attention", async () => {
  let releaseRuns: (runs: RunSummary[]) => void = () => {}
  let runsStarted: () => void = () => {}
  const secondRunsStarted = new Promise<void>((resolve) => {
    runsStarted = resolve
  })
  const pendingRuns = new Promise<RunSummary[]>((resolve) => {
    releaseRuns = resolve
  })
  const fetchRuns = vi
    .fn()
    .mockResolvedValueOnce([])
    .mockImplementationOnce(() => {
      runsStarted()
      return pendingRuns
    })
  const { store, feed } = harness({ fetchRuns })
  await store.start()

  const resynced = store.resync()
  await secondRunsStarted
  feed().onEvent({ ...CHANGED_RUN, type: "run_summary" })
  releaseRuns([CHANGED_RUN])
  await resynced

  expect(store.getStage().tasks["board/chores"].pending).toBe(1)
  store.stop()
})

test("summaries already reflected by the task listing do not increment review twice", async () => {
  const quietRun = {
    ...CHANGED_RUN,
    run_id: "quiet-after-change",
    started_at: "2026-08-31T10:00:00Z",
    finished_at: "2026-08-31T10:00:05Z",
    said: "nothing else to do",
    change: undefined,
  }
  let releaseListing: (value: Listing) => void = () => {}
  let listingStarted: () => void = () => {}
  const secondListingStarted = new Promise<void>((resolve) => {
    listingStarted = resolve
  })
  const pendingListing = new Promise<Listing>((resolve) => {
    releaseListing = resolve
  })
  const fetchTasks = vi
    .fn()
    .mockResolvedValueOnce(listing([CHORES]))
    .mockImplementationOnce(() => {
      listingStarted()
      return pendingListing
    })
  const fetchRuns = vi
    .fn()
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([quietRun, CHANGED_RUN])
  const { store, feed } = harness({ fetchTasks, fetchRuns })
  await store.start()

  const resynced = store.resync()
  await secondListingStarted
  feed().onEvent({ ...CHANGED_RUN, type: "run_summary" })
  feed().onEvent({ ...quietRun, type: "run_summary" })
  releaseListing(listing([{ ...CHORES, pending: 1, last_run: quietRun }]))
  await resynced

  expect(store.getStage().tasks["board/chores"].pending).toBe(1)
  store.stop()
})

test("a resync refreshes what finished while the feed was down", async () => {
  const summary = {
    run_id: "r-old",
    task: "chores",
    project: "board",
    graph: "agent-task",
    status: "completed",
    started_at: "2026-08-22T07:00:00+00:00",
    finished_at: "2026-08-22T07:00:01+00:00",
    steps: 4,
    iteration: 1,
    trigger: "cron 0 2 * * *",
    usage: {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
    },
    error: null,
    said: "did the thing",
  }
  const { store } = harness({
    fetchTasks: vi.fn(async () => listing([{ ...CHORES, last_run: summary }])),
  })
  await store.start()
  await store.resync()

  // The run_summary frame for that run was missed; /api/tasks still knows.
  expect(store.getStage().tasks["board/chores"].lastRun).toEqual({
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


test("a resync asks the tasks together, not one after another", async () => {
  // Resync fires on every reconnect -- exactly when the board is already
  // stale -- and live frames queue until it finishes. One round trip per task,
  // in single file, holds the board hostage for tasks x latency.
  const tasks = ["a", "b", "c"].map((name) => ({
    ...CHORES,
    name,
    current_run_id: `run-${name}`,
  }))

  let active = 0
  let peak = 0
  const slow = async <T,>(value: T): Promise<T> => {
    active += 1
    peak = Math.max(peak, active)
    await new Promise((resolve) => setTimeout(resolve, 5))
    active -= 1
    return value
  }

  const { store } = harness({
    fetchTasks: vi.fn(async () => listing(tasks)),
    fetchRuns: vi.fn(() => slow([])),
    fetchRunEvents: vi.fn(() => slow([] as PoieoEvent[])),
  })
  await store.start()

  peak = 0 // measure the resync alone, not start()'s own tally
  await store.resync()
  expect(peak).toBeGreaterThan(1) // overlapping, not sequential
  store.stop()
})


test("the store tallies each task's recent work from the run index", async () => {
  const runs = [
    {
      run_id: "a",
      task: "chores",
      project: "board",
      graph: "agent-task",
      status: "completed",
      started_at: "t",
      finished_at: "t",
      steps: 1,
      iteration: 1,
      trigger: "cron 0 2 * * *",
      usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
      error: null,
      said: "did the thing",
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
  expect(store.getStage().tasks["board/chores"].recent).toMatchObject({
    runs: 1,
    succeeded: 1,
    insertions: 9,
  })
  store.stop()
})

test("a task stopped while the page was open survives the next read", async () => {
  // The listing is authoritative about a hold, because nothing is published
  // when somebody presses pause. This fold used to flatten every state that
  // was not `running` back to `waiting` on its way in, so the board forgot a
  // pause on the very next resync -- including the one the press itself
  // triggers, which made the button look like it had done nothing.
  const rows = [{ ...CHORES, status: "paused", holding: true }]
  const { store } = harness({ fetchTasks: vi.fn(async () => listing(rows)) })
  await store.start()
  await store.resync()

  expect(store.getStage().tasks["board/chores"].status).toBe("paused")
  expect(store.getStage().tasks["board/chores"].held).toBe(true)
  store.stop()
})

test("a run that died still reads as stopped after a resync", async () => {
  // The other half, and why the fold cannot simply take the listing's word:
  // the daemon calls a task whose run failed `waiting` again, and only the
  // event stream ever saw the failure.
  const { store, feed } = harness()
  await store.start()
  for (const event of AGENT_RUN.slice(0, 2)) feed().onEvent(event)
  feed().onEvent({ run_id: AGENT_RUN[0].run_id, type: "run_failed", at: "", data: {} })
  expect(store.getStage().tasks["board/chores"].status).toBe("error")

  await store.resync()
  expect(store.getStage().tasks["board/chores"].status).toBe("error")
  store.stop()
})

test("a newer successful run clears an old live failure on resync", async () => {
  const failed = {
    ...CHANGED_RUN,
    run_id: "failed-old",
    status: "failed",
    finished_at: "2026-08-31T08:00:05Z",
    error: "endpoint stopped",
    change: undefined,
  } as RunSummary
  const recovered = {
    ...CHANGED_RUN,
    run_id: "recovered-new",
    finished_at: "2026-08-31T10:00:05Z",
    said: "recovered",
    change: undefined,
  }
  const fetchTasks = vi
    .fn()
    .mockResolvedValueOnce(listing([CHORES]))
    .mockResolvedValueOnce(listing([{ ...CHORES, last_run: recovered }]))
  const fetchRuns = vi.fn().mockResolvedValueOnce([]).mockResolvedValueOnce([recovered])
  const { store, feed } = harness({ fetchTasks, fetchRuns })
  await store.start()

  feed().onEvent({
    run_id: failed.run_id,
    type: "run_started",
    data: { task: "chores", project: "board" },
  })
  feed().onEvent({ run_id: failed.run_id, type: "run_failed", data: {} })
  feed().onEvent({ ...failed, type: "run_summary" })
  expect(store.getStage().tasks["board/chores"].status).toBe("error")

  await store.resync()
  expect(store.getStage().tasks["board/chores"].status).toBe("waiting")
  store.stop()
})
