import { expect, test } from "vitest"

import { changedTasks } from "./changed"
import { initialStage, reduce } from "../state/stage"
import type { TaskState } from "../state/stage"
import type { TaskRow } from "../types"

const row = (name: string): TaskRow => ({
  name,
  project: "board",
  graph: "g",
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
})

test("every task is changed the first time a skin sees it", () => {
  const stage = initialStage([row("a"), row("b")])
  const painted = new Map<string, TaskState>()
  expect(changedTasks(stage.tasks, painted).map(([task]) => task)).toEqual(["board/a", "board/b"])
})

test("a frame that touched one task repaints one task", () => {
  const stage = initialStage([row("a"), row("b")])
  const painted = new Map<string, TaskState>()
  changedTasks(stage.tasks, painted)

  const next = reduce(stage, {
    run_id: "r1",
    type: "run_started",
    data: { task: "a", project: "board" },
  })
  expect(changedTasks(next.tasks, painted).map(([task]) => task)).toEqual(["board/a"])
  // and painting it once is enough
  expect(changedTasks(next.tasks, painted)).toEqual([])
})

test("a task that leaves the board is forgotten, so its return repaints", () => {
  const stage = initialStage([row("a")])
  const painted = new Map<string, TaskState>()
  changedTasks(stage.tasks, painted)

  changedTasks({}, painted) // the task disappears
  expect(painted.size).toBe(0)

  expect(changedTasks(stage.tasks, painted).map(([task]) => task)).toEqual(["board/a"])
})
