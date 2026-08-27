import { expect, test } from "vitest"

import {
  CELL,
  ZOOM,
  bounds,
  cellAt,
  cellOrigin,
  clampZoom,
  columnsFor,
  figurePose,
  fit,
  lampLit,
  occupied,
  place,
  shelfCount,
} from "./scene"
import { NOTHING } from "../../review/rollup"
import type { TaskState } from "../../state/stage"

function flowState(over: Partial<TaskState> = {}): TaskState {
  return {
    status: "waiting",
    currentNode: null,
    nodeType: null,
    step: 0,
    turn: 0,
    lastText: "",
    lastThinking: "",
    recentToolCalls: [],
    lastRun: null,
    recent: NOTHING,
    runs: [],
    tracked: true,
    then: [],
    shape: { entry: "", nodes: [] },
    trigger: "",
    ...over,
  }
}

test("a square maps to a screen offset and back", () => {
  const cell = { col: 2, row: 1 }
  const at = cellOrigin(cell)

  expect(at).toEqual({ x: 2 * CELL.width, y: CELL.height })
  expect(cellAt(at.x, at.y)).toEqual(cell)
})

test("a bench dropped between squares lands on the nearest one", () => {
  // Benches never sit half on a square: that is what makes overlap decidable.
  expect(cellAt(CELL.width * 0.6, CELL.height * 0.4)).toEqual({ col: 1, row: 0 })
  expect(cellAt(CELL.width * 0.4, CELL.height * 0.6)).toEqual({ col: 0, row: 1 })
})

test("occupied sees other benches but not the one being moved", () => {
  const placed = { a: { col: 0, row: 0 }, b: { col: 1, row: 0 } }

  expect(occupied(placed, { col: 1, row: 0 }, "a")).toBe(true)
  expect(occupied(placed, { col: 1, row: 0 }, "b")).toBe(false) // its own square
  expect(occupied(placed, { col: 2, row: 0 }, "a")).toBe(false)
})

test("the automatic arrangement fills squares in order", () => {
  const placed = place(["a", "b", "c"], {}, 2)

  expect(placed.a).toEqual({ col: 0, row: 0 })
  expect(placed.b).toEqual({ col: 1, row: 0 })
  expect(placed.c).toEqual({ col: 0, row: 1 })
})

test("no two benches can share a square", () => {
  // A saved square that is already taken loses to the bench standing there.
  const placed = place(["a", "b"], { b: { col: 0, row: 0 } }, 3)

  expect(placed.b).toEqual({ col: 0, row: 0 })
  expect(placed.a).not.toEqual(placed.b)
})

test("a saved square for a task that is gone is ignored", () => {
  const placed = place(["a"], { ghost: { col: 4, row: 4 } }, 3)
  expect(Object.keys(placed)).toEqual(["a"])
})

test("a phone gets a single column, a monitor gets several", () => {
  expect(columnsFor(390)).toBe(1)
  expect(columnsFor(1400)).toBeGreaterThan(1)
})

test("a column of benches fits a phone without shrinking", () => {
  const placed = place(["a", "b", "c"], {}, columnsFor(390))
  const box = bounds(Object.values(placed))

  expect(box.width).toBeLessThanOrEqual(390)
  expect(fit(box, { width: 390, height: 780 })).toBe(1)
})

test("bounds covers the drawn bench, not just its origin", () => {
  const box = bounds([{ col: 0, row: 0 }])

  expect(box.x).toBe(-CELL.width / 2)
  expect(box.width).toBe(CELL.width)
})

test("the room shrinks to fit a screen it cannot fill", () => {
  const box = { width: 840, height: 500 }

  expect(fit(box, { width: 390, height: 780 })).toBeLessThan(1)
  expect(fit(box, { width: 2400, height: 1200 })).toBe(1)
})

test("the room never shrinks to nothing", () => {
  expect(fit({ width: 9000, height: 9000 }, { width: 320, height: 480 })).toBe(0.35)
})

test("an empty room needs no scaling", () => {
  expect(fit({ width: 0, height: 0 }, { width: 390, height: 700 })).toBe(1)
})

test("zoom is bounded on both sides", () => {
  expect(clampZoom(99)).toBe(ZOOM.max)
  expect(clampZoom(0.001)).toBe(ZOOM.min)
  expect(clampZoom(1.4)).toBe(1.4)
})

test("figurePose maps the three states to three poses", () => {
  const poses = new Set([
    figurePose(flowState({ status: "waiting" })),
    figurePose(flowState({ status: "running" })),
    figurePose(flowState({ status: "error" })),
  ])
  expect(poses.size).toBe(3)
})

test("the lamp is lit while the bench is in use", () => {
  expect(lampLit(flowState({ status: "running" }))).toBe(true)
  expect(lampLit(flowState({ status: "waiting" }))).toBe(false)
})

test("a task with no private copy shelves nothing", () => {
  // It produces no piece to put anywhere. Counting its runs as finished
  // pieces fills a shelf with things that do not exist.
  const busy = flowState({
    tracked: false,
    recent: { ...NOTHING, runs: 40, succeeded: 40 },
  })
  expect(shelfCount(busy)).toBe(0)
})

test("the shelf fills with finished work, not attempts", () => {
  expect(shelfCount(flowState())).toBe(0)
  expect(shelfCount(flowState({ recent: { ...NOTHING, runs: 4, succeeded: 3 } }))).toBe(3)
  // a failed night leaves the shelf empty
  expect(shelfCount(flowState({ recent: { ...NOTHING, runs: 2, failed: 2 } }))).toBe(0)
})


