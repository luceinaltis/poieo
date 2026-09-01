import { expect, test } from "vitest"

import {
  AGENT_RUN,
  AGENT_SUMMARY,
  FAILED_RUN,
  FAILED_SUMMARY,
  LLM_RUN,
} from "./fixtures"
import { WINDOW, initialStage, reduce, replay, setRuns } from "./stage"
import type { StageState } from "./stage"
import type { TaskRow, PoieoEvent, RunSummary } from "../types"

const TASK_ROWS: TaskRow[] = [
  {
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
  },
  {
    name: "revision",
    project: "board",
    graph: "draft-review",
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
  },
]

const start = () => initialStage(TASK_ROWS)

test("initialStage seeds one state per task", () => {
  const stage = start()
  expect(Object.keys(stage.tasks)).toEqual(["board/chores", "board/revision"])
  expect(stage.tasks["board/chores"].status).toBe("waiting")
  expect(stage.tasks["board/chores"].currentNode).toBeNull()
})

test("a full run walks waiting -> running -> waiting", () => {
  let stage = start()
  const seen: string[] = []
  for (const event of AGENT_RUN) {
    stage = reduce(stage, event)
    seen.push(stage.tasks["board/chores"].status)
  }
  expect(seen[0]).toBe("running")
  expect(seen.at(-1)).toBe("waiting")
  expect(stage.tasks["board/chores"].currentNode).toBeNull()
  // the other task never moved
  expect(stage.tasks["board/revision"].status).toBe("waiting")
})

test("node_turn records text and thinking", () => {
  const stage = replay(start(), AGENT_RUN)
  const turns = AGENT_RUN.filter((e) => e.type === "node_turn")
  expect(stage.tasks["board/chores"].turn).toBe(turns.length)
  // the mock's first turn thinks out loud before reaching for a tool
  const first = replay(start(), AGENT_RUN.slice(0, 3))
  expect(first.tasks["board/chores"].lastThinking).toBe("First see what is in this directory.")
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
  const calls = replay(start(), many).tasks["board/chores"].recentToolCalls
  expect(calls).toHaveLength(8)
  expect(calls[0].name).toBe("tool_10")
  expect(calls.at(-1)!.name).toBe("tool_3")
})

test("a tool call carries what it acted on and what came back", () => {
  // A column of bare "read_file" says nothing. The path is the whole point.
  const stage = replay(start(), [
    AGENT_RUN[0],
    {
      run_id: AGENT_RUN[0].run_id,
      type: "node_tool_call",
      at: "2026-08-22T07:28:19.838+00:00",
      node_id: "work",
      data: {
        turn: 1,
        name: "read_file",
        // the daemon clips arguments to a JSON string before writing them
        arguments: '{"path": "DESIGN.md"}',
        result: "# poieo Design",
        error: false,
      },
    },
  ])
  const call = stage.tasks["board/chores"].recentToolCalls[0]
  expect(call.subject).toBe("DESIGN.md")
  expect(call.result).toBe("# poieo Design")
  expect(call.failed).toBe(false)
})

test("a failed tool call is marked failed, and error is a boolean", () => {
  // The daemon writes `error: bool`; reading it as a string marked nothing.
  const stage = replay(start(), [
    AGENT_RUN[0],
    {
      run_id: AGENT_RUN[0].run_id,
      type: "node_tool_call",
      at: "2026-08-22T07:28:19.838+00:00",
      node_id: "work",
      data: {
        turn: 1,
        name: "read_file",
        arguments: '{"path": "nope.md"}',
        result: "no such file: nope.md",
        error: true,
      },
    },
  ])
  expect(stage.tasks["board/chores"].recentToolCalls[0].failed).toBe(true)
})

test("node_finished does not clear the current node", () => {
  // Between two nodes the board should hold the last one, not blink to empty.
  const upToFirstFinish = LLM_RUN.slice(0, 3)
  expect(upToFirstFinish.at(-1)!.type).toBe("node_finished")
  const stage = replay(start(), upToFirstFinish)
  expect(stage.tasks["board/revision"].currentNode).toBe("draft")
})

test("run_failed puts the task in error", () => {
  const stage = replay(start(), FAILED_RUN)
  expect(stage.tasks["board/chores"].status).toBe("error")
  expect(stage.tasks["board/chores"].currentNode).toBeNull()
})

test("run_summary reads flat fields and fills lastRun", () => {
  const stage = reduce(replay(start(), AGENT_RUN), AGENT_SUMMARY)
  expect(stage.tasks["board/chores"].lastRun).toEqual({
    status: "completed",
    steps: AGENT_SUMMARY.steps,
    finished_at: AGENT_SUMMARY.finished_at,
  })
  // a summary also retires the run it describes
  expect(stage.runTask[AGENT_SUMMARY.run_id]).toBeUndefined()
})

test("a failed run's summary still lands", () => {
  const stage = reduce(replay(start(), FAILED_RUN), FAILED_SUMMARY)
  expect(stage.tasks["board/chores"].lastRun!.status).toBe("failed")
})

test("replaying history then applying the live overlap is idempotent", () => {
  // What a browser arriving mid-run actually does: read the run so far, then
  // keep taking live frames that overlap what it just read.
  const inFlight = AGENT_RUN.slice(0, -1)
  const once = replay(start(), inFlight)
  const twice = replay(once, inFlight.slice(2))
  expect(twice.tasks).toEqual(once.tasks)
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

test("an ad-hoc run with no task stays off the board", () => {
  // `poieo run` writes task: null; only daemon tasks belong on the stage.
  const stage = start()
  const adhoc: PoieoEvent = {
    run_id: "adhoc",
    type: "run_started",
    at: "2026-08-22T07:00:00+00:00",
    data: { graph: "agent-task", task: null, iteration: 1 },
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
  expect(replay(start(), AGENT_RUN).tasks).toEqual(folded.tasks)
})

test("a run summary adds to the task's recent tally", () => {
  const stage = reduce(replay(start(), AGENT_RUN), AGENT_SUMMARY)

  expect(stage.tasks["board/chores"].recent.runs).toBe(1)
  // the fixture run changed nothing the store recorded, so it is a quiet run
  expect(stage.tasks["board/chores"].recent.failed).toBe(0)
})

test("a failed run's summary is tallied as failed", () => {
  const stage = reduce(replay(start(), FAILED_RUN), FAILED_SUMMARY)

  expect(stage.tasks["board/chores"].recent.failed).toBe(1)
  expect(stage.tasks["board/chores"].recent.succeeded).toBe(0)
})

function aRun(run_id: string, overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id,
    task: "chores",
    project: "board",
    graph: "agent-task",
    status: "completed",
    started_at: "2026-08-27T02:00:00+00:00",
    finished_at: "2026-08-27T02:00:04+00:00",
    steps: 1,
    iteration: 1,
    trigger: "cron",
    usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
    error: null,
    said: "did the thing",
    ...overrides,
  }
}

test("setRuns seeds the window the events cannot supply", () => {
  const seeded = setRuns(start(), "board/chores", [
    aRun("a", { change: { base: "x", head: "y", files: ["f"], insertions: 40, deletions: 2, message: "did" } }),
    aRun("b", { change: { base: "x", head: "y", files: ["f"], insertions: 0, deletions: 0, message: "did" } }),
    aRun("c", { status: "failed", error: "boom" }),
  ])

  expect(seeded.tasks["board/chores"].recent.runs).toBe(3)
  expect(seeded.tasks["board/chores"].recent.failed).toBe(1)
  expect(seeded.tasks["board/chores"].recent.insertions).toBe(40)
  expect(seeded.tasks["board/revision"].recent.runs).toBe(0)
  expect(setRuns(seeded, "ghost", [])).toBe(seeded)
})

test("the tally stays inside the window the work list shows", () => {
  // The card's number and the list below it are the same runs, or the reader
  // has no way to tell which of them is lying. Live summaries used to fold in
  // without a bound, so a page left open all night drifted past both.
  const seeded = setRuns(
    start(),
    "board/chores",
    Array.from({ length: WINDOW }, (_, i) => aRun(`seed${i}`)),
  )
  expect(seeded.tasks["board/chores"].recent.runs).toBe(WINDOW)

  const after = reduce(seeded, {
    run_id: "fresh",
    type: "run_summary",
    task: "chores",
    project: "board",
    status: "completed",
    steps: 1,
    finished_at: "2026-08-27T02:00:00+00:00",
  })

  expect(after.tasks["board/chores"].recent.runs).toBe(WINDOW)
  expect(after.tasks["board/chores"].runs[0].run_id).toBe("fresh")
})

test("a summary for a task that is not on the board changes nothing", () => {
  const state = start()
  expect(
    reduce(state, { run_id: "r", type: "run_summary", task: "ghost", status: "completed" }),
  ).toBe(state)
})


test("two projects may each have a chores, and they do not become one", () => {
  // The whole reason the key is a pair. Filed under the task name alone,
  // the second project's chores landed on top of the first's and the board
  // showed one card doing two things.
  const rows = [
    { ...TASK_ROWS[0], project: "night shift" },
    { ...TASK_ROWS[0], project: "day job" },
  ]
  const stage = initialStage(rows)

  expect(Object.keys(stage.tasks)).toEqual(["night shift/chores", "day job/chores"])

  const running = reduce(stage, {
    run_id: "r1",
    type: "run_started",
    data: { task: "chores", project: "day job" },
  })
  expect(running.tasks["day job/chores"].status).toBe("running")
  expect(running.tasks["night shift/chores"].status).toBe("waiting")
})


test("a task still knows what it is called, whatever it is filed under", () => {
  const stage = initialStage([{ ...TASK_ROWS[0], project: "night shift" }])
  const one = stage.tasks["night shift/chores"]

  expect(one.name).toBe("chores")
  expect(one.project).toBe("night shift")
})

// -- what a task is doing, when it is not running --------------------------
//
// The board used to fold every state that was not `running` into `waiting`,
// so a task somebody had stopped looked exactly like one between two runs.

test("a paused task is not folded into waiting", () => {
  const stage = initialStage([{ ...TASK_ROWS[0], status: "paused", holding: true }])
  expect(stage.tasks["board/chores"].status).toBe("paused")
})

test("a task held back by its budget reads as paused too", () => {
  // Not the same reason, but the same answer to the question the board is
  // asked: this one is not going to run right now.
  const stage = initialStage([{ ...TASK_ROWS[0], status: "over budget", holding: false }])
  expect(stage.tasks["board/chores"].status).toBe("paused")
})

test("a hold survives the run it was pressed during", () => {
  // Pause takes effect between runs, so the run in flight finishes first --
  // and `run_finished` parked the board back on `waiting`, which is what an
  // unpaused task looks like. Nothing asks the daemon again until the page
  // reconnects, so the board stayed wrong for as long as it was open.
  let stage = initialStage([
    { ...TASK_ROWS[0], status: "running", current_run_id: "r1", holding: true },
  ])
  stage = reduce(stage, { run_id: "r1", type: "run_started", at: "", data: { task: "chores", project: "board" } })
  expect(stage.tasks["board/chores"].status).toBe("running")
  stage = reduce(stage, { run_id: "r1", type: "run_finished", at: "", data: { steps: 1 } })
  expect(stage.tasks["board/chores"].status).toBe("paused")
})

test("a run finishing on a task nobody held leaves it waiting", () => {
  let stage = initialStage([{ ...TASK_ROWS[0], holding: false }])
  stage = reduce(stage, { run_id: "r1", type: "run_started", at: "", data: { task: "chores", project: "board" } })
  stage = reduce(stage, { run_id: "r1", type: "run_finished", at: "", data: { steps: 1 } })
  expect(stage.tasks["board/chores"].status).toBe("waiting")
})
