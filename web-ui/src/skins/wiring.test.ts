import { expect, test } from "vitest"

import { BOX, exits, place, walk, wire } from "./wiring"
import type { GraphShape } from "../types"

const LINE: GraphShape = {
  entry: "draft",
  nodes: [
    { id: "draft", type: "llm", next: "review", default: null, branches: [] },
    { id: "review", type: "llm", next: "gate", default: null, branches: [] },
    {
      id: "gate",
      type: "router",
      next: null,
      default: "revise",
      branches: [{ to: null, label: "approved" }],
    },
    { id: "revise", type: "llm", next: "review", default: null, branches: [] },
  ],
}

test("a board with no handoffs is one column, not a failure to lay out", () => {
  const placed = place(["a", "b", "c"], {})

  expect(placed.map((p) => p.column)).toEqual([0, 0, 0])
  expect(placed.map((p) => p.row)).toEqual([0, 1, 2])
})

test("a flow sits to the right of whatever hands to it", () => {
  const placed = place(["chores", "review", "publish"], {
    chores: ["review"],
    review: ["publish"],
  })

  expect(placed).toEqual([
    { flow: "chores", column: 0, row: 0 },
    { flow: "review", column: 1, row: 0 },
    { flow: "publish", column: 2, row: 0 },
  ])
})

test("two flows fed by one stack up in the same column", () => {
  const placed = place(["chores", "review", "alert"], { chores: ["review", "alert"] })

  expect(placed.slice(1)).toEqual([
    { flow: "review", column: 1, row: 0 },
    { flow: "alert", column: 1, row: 1 },
  ])
})

test("a flow waits for its furthest sender, not its nearest", () => {
  // chores -> review -> publish, and chores -> publish as well. publish must
  // land past review, or the long arrow would point backwards on screen.
  const placed = place(["chores", "review", "publish"], {
    chores: ["review", "publish"],
    review: ["publish"],
  })

  expect(placed.find((p) => p.flow === "publish")?.column).toBe(2)
})

test("a cycle is drawn rather than refused", () => {
  const placed = place(["fix", "review"], { fix: ["review"], review: ["fix"] })

  // Nothing can be peeled, so both land together and the loop is still visible.
  expect(placed).toHaveLength(2)
  expect(placed.every((p) => typeof p.column === "number")).toBe(true)
})

test("a handoff naming a flow that is not on the board is ignored", () => {
  const placed = place(["chores"], { chores: ["gone"] })

  expect(placed).toEqual([{ flow: "chores", column: 0, row: 0 }])
})

test("a walk reads entry first and every node once, loop or not", () => {
  expect(walk(LINE)).toEqual(["draft", "review", "gate", "revise"])
})

test("a node the walk cannot reach is drawn last rather than dropped", () => {
  const stray: GraphShape = {
    ...LINE,
    nodes: [...LINE.nodes, { id: "orphan", type: "llm", next: null, default: null, branches: [] }],
  }

  expect(walk(stray)).toContain("orphan")
})

test("an exit is a node the run can stop on", () => {
  // `gate` has a branch going nowhere, so the run can end there. `revise`
  // loops back to review, so it cannot.
  expect(exits(LINE)).toEqual(["gate"])
})

test("a node with nowhere to go next is an exit", () => {
  const stops: GraphShape = {
    entry: "only",
    nodes: [{ id: "only", type: "llm", next: null, default: null, branches: [] }],
  }

  expect(exits(stops)).toEqual(["only"])
})

test("a box that opens does not drag its arrows down with it", () => {
  const [from, to] = place(["chores", "review"], { chores: ["review"] })

  // Level with the header, which is a fixed distance from the top edge --
  // not the middle, which moves as soon as a box grows a graph inside it.
  expect(wire(from, to).y1).toBe(wire(from, to).y2)
  expect(wire(from, to).y1).toBe(BOX.head)
})

test("an arrow leaves one box's right edge and enters the next one's left", () => {
  const [from, to] = place(["chores", "review"], { chores: ["review"] })
  const line = wire(from, to)

  expect(line.x1).toBe(BOX.width)
  expect(line.x2).toBe(BOX.width + BOX.gapX)
})
