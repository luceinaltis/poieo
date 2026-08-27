import { expect, test } from "vitest"

import { changedFlows } from "./changed"
import { initialStage, reduce } from "../state/stage"
import type { FlowState } from "../state/stage"
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
  then: [],
  shape: { entry: "", nodes: [] },
})

test("every flowState is changed the first time a skin sees it", () => {
  const stage = initialStage([row("a"), row("b")])
  const painted = new Map<string, FlowState>()
  expect(changedFlows(stage.flows, painted).map(([flow]) => flow)).toEqual(["a", "b"])
})

test("a frame that touched one flow repaints one flow", () => {
  const stage = initialStage([row("a"), row("b")])
  const painted = new Map<string, FlowState>()
  changedFlows(stage.flows, painted)

  const next = reduce(stage, {
    run_id: "r1",
    type: "run_started",
    data: { flow: "a" },
  })
  expect(changedFlows(next.flows, painted).map(([flow]) => flow)).toEqual(["a"])
  // and painting it once is enough
  expect(changedFlows(next.flows, painted)).toEqual([])
})

test("a flow that leaves the board is forgotten, so its return repaints", () => {
  const stage = initialStage([row("a")])
  const painted = new Map<string, FlowState>()
  changedFlows(stage.flows, painted)

  changedFlows({}, painted) // the flow disappears
  expect(painted.size).toBe(0)

  expect(changedFlows(stage.flows, painted).map(([flow]) => flow)).toEqual(["a"])
})
