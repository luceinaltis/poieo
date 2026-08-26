import { expect, test } from "vitest"

import { changedWorkers } from "./changed"
import { initialStage, reduce } from "../state/stage"
import type { Worker } from "../state/stage"
import type { FlowRow } from "../types"

const row = (name: string): FlowRow => ({
  name,
  graph: "g",
  trigger: "loop",
  status: "waiting",
  current_run_id: null,
  last_run: null,
  pending: 0,
  into: null,
})

test("every worker is changed the first time a skin sees it", () => {
  const stage = initialStage([row("a"), row("b")])
  const painted = new Map<string, Worker>()
  expect(changedWorkers(stage.workers, painted).map(([flow]) => flow)).toEqual(["a", "b"])
})

test("a frame that touched one flow repaints one flow", () => {
  const stage = initialStage([row("a"), row("b")])
  const painted = new Map<string, Worker>()
  changedWorkers(stage.workers, painted)

  const next = reduce(stage, {
    run_id: "r1",
    type: "run_started",
    data: { flow: "a" },
  })
  expect(changedWorkers(next.workers, painted).map(([flow]) => flow)).toEqual(["a"])
  // and painting it once is enough
  expect(changedWorkers(next.workers, painted)).toEqual([])
})

test("a flow that leaves the board is forgotten, so its return repaints", () => {
  const stage = initialStage([row("a")])
  const painted = new Map<string, Worker>()
  changedWorkers(stage.workers, painted)

  changedWorkers({}, painted) // the flow disappears
  expect(painted.size).toBe(0)

  expect(changedWorkers(stage.workers, painted).map(([flow]) => flow)).toEqual(["a"])
})
