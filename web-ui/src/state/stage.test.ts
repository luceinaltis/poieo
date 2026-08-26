import { expect, test } from "vitest"

import {
  AGENT_RUN,
  AGENT_SUMMARY,
  FAILED_RUN,
  FAILED_SUMMARY,
  LLM_RUN,
} from "./fixtures"
import { initialStage, reduce, replay, setRecent } from "./stage"
import { NOTHING } from "../review/rollup"
import type { StageState } from "./stage"
import type { FlowRow, PoieoEvent } from "../types"

const FLOWS: FlowRow[] = [
  {
    name: "chores",
    graph: "agent-task",
    trigger: "loop",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: null,
    then: [],
    shape: { entry: "", nodes: [] },
  },
  {
    name: "revision",
    graph: "draft-review",
    trigger: "loop",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: null,
    then: [],
    shape: { entry: "", nodes: [] },
  },
]

const start = () => initialStage(FLOWS)

test("initialStage seeds one worker per flow", () => {
  const stage = start()
  expect(Object.keys(stage.workers)).toEqual(["chores", "revision"])
  expect(stage.workers.chores.status).toBe("waiting")
  expect(stage.workers.chores.currentNode).toBeNull()
})

test("a full run walks waiting -> running -> waiting", () => {
  let stage = start()
  const seen: string[] = []
  for (const event of AGENT_RUN) {
    stage = reduce(stage, event)
    seen.push(stage.workers.chores.status)
  }
  expect(seen[0]).toBe("running")
  expect(seen.at(-1)).toBe("waiting")
  expect(stage.workers.chores.currentNode).toBeNull()
  // the other flow never moved
  expect(stage.workers.revision.status).toBe("waiting")
})

test("node_turn records text and thinking", () => {
  const stage = replay(start(), AGENT_RUN)
  const turns = AGENT_RUN.filter((e) => e.type === "node_turn")
  expect(stage.workers.chores.turn).toBe(turns.length)
  // the mock's first turn thinks out loud before reaching for a tool
  const first = replay(start(), AGENT_RUN.slice(0, 3))
  expect(first.workers.chores.lastThinking).toBe("First see what is in this directory.")
})

test("tool calls accumulate newest-first and cap at 8", () => {
  const many: PoieoEvent[] = [AGENT_RUN[0]]
  for (let i = 1; i <= 10; i += 1) {
    many.push({
      run_id: AGENT_RUN[0].run_id,
      type: "node_tool_call",
      at: `2026-08-22T07:28:19.${String(i).padStart(3, "0")}+00:00`,
      node_id: "work",
      data: { turn: i, name: `tool_${i}`, error: null, result: "", arguments: {} },
    })
  }
  const calls = replay(start(), many).workers.chores.recentToolCalls
  expect(calls).toHaveLength(8)
  expect(calls[0].name).toBe("tool_10")
  expect(calls.at(-1)!.name).toBe("tool_3")
})

test("node_finished does not clear the current node", () => {
  // Between two nodes the board should hold the last one, not blink to empty.
  const upToFirstFinish = LLM_RUN.slice(0, 3)
  expect(upToFirstFinish.at(-1)!.type).toBe("node_finished")
  const stage = replay(start(), upToFirstFinish)
  expect(stage.workers.revision.currentNode).toBe("draft")
})

test("run_failed puts the worker in error", () => {
  const stage = replay(start(), FAILED_RUN)
  expect(stage.workers.chores.status).toBe("error")
  expect(stage.workers.chores.currentNode).toBeNull()
})

test("run_summary reads flat fields and fills lastRun", () => {
  const stage = reduce(replay(start(), AGENT_RUN), AGENT_SUMMARY)
  expect(stage.workers.chores.lastRun).toEqual({
    status: "completed",
    steps: AGENT_SUMMARY.steps,
    finished_at: AGENT_SUMMARY.finished_at,
  })
  // a summary also retires the run it describes
  expect(stage.runFlow[AGENT_SUMMARY.run_id as string]).toBeUndefined()
})

test("a failed run's summary still lands", () => {
  const stage = reduce(replay(start(), FAILED_RUN), FAILED_SUMMARY)
  expect(stage.workers.chores.lastRun!.status).toBe("failed")
})

test("replaying history then applying the live overlap is idempotent", () => {
  // What a browser arriving mid-run actually does: read the run so far, then
  // keep taking live frames that overlap what it just read.
  const inFlight = AGENT_RUN.slice(0, -1)
  const once = replay(start(), inFlight)
  const twice = replay(once, inFlight.slice(2))
  expect(twice.workers).toEqual(once.workers)
})

test("events for an unknown run are ignored", () => {
  const stage = start()
  const orphan: PoieoEvent = {
    run_id: "never-announced",
    type: "node_started",
    at: "2026-08-22T07:00:00+00:00",
    node_id: "work",
    data: { type: "agent", step: 1 },
  }
  expect(reduce(stage, orphan)).toBe(stage)
})

test("an ad-hoc run with no flow stays off the board", () => {
  // `poieo run` writes flow: null; only daemon flows belong on the stage.
  const stage = start()
  const adhoc: PoieoEvent = {
    run_id: "adhoc",
    type: "run_started",
    at: "2026-08-22T07:00:00+00:00",
    data: { graph: "agent-task", flow: null, iteration: 1 },
  }
  const after = reduce(stage, adhoc)
  expect(after).toBe(stage)
  expect(reduce(after, { ...AGENT_RUN[1], run_id: "adhoc" })).toBe(stage)
})

test("an unknown event type leaves the state untouched", () => {
  const stage = replay(start(), AGENT_RUN.slice(0, 1))
  const future: PoieoEvent = {
    run_id: AGENT_RUN[0].run_id,
    type: "node_vibed",
    at: "2026-08-22T07:28:20+00:00",
    data: {},
  }
  expect(reduce(stage, future)).toBe(stage)
})

test("replay equals folding one at a time", () => {
  const folded = AGENT_RUN.reduce<StageState>((s, e) => reduce(s, e), start())
  expect(replay(start(), AGENT_RUN).workers).toEqual(folded.workers)
})

test("a run summary adds to the flow's recent tally", () => {
  const stage = reduce(replay(start(), AGENT_RUN), AGENT_SUMMARY)

  expect(stage.workers.chores.recent.runs).toBe(1)
  // the fixture run changed nothing the store recorded, so it is a quiet run
  expect(stage.workers.chores.recent.failed).toBe(0)
})

test("a failed run's summary is tallied as failed", () => {
  const stage = reduce(replay(start(), FAILED_RUN), FAILED_SUMMARY)

  expect(stage.workers.chores.recent.failed).toBe(1)
  expect(stage.workers.chores.recent.succeeded).toBe(0)
})

test("setRecent seeds a tally the events cannot supply", () => {
  const seeded = setRecent(start(), "chores", {
    runs: 3,
    succeeded: 2,
    failed: 1,
    nothingToDo: 0,
    insertions: 40,
    deletions: 2,
  })

  expect(seeded.workers.chores.recent.runs).toBe(3)
  expect(seeded.workers.revision.recent.runs).toBe(0)
  expect(setRecent(seeded, "ghost", NOTHING)).toBe(seeded)
})
