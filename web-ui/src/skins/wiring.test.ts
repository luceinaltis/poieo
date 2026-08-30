import { expect, test } from "vitest"

import {
  BOX, arrivals, backWire, centreOn, corner, depths, exits, fit, looking, loops, minimap, pan,
  place, walk, wire, zoom,
} from "./wiring"
import type { GraphShape } from "../types"

const LINE: GraphShape = {
  entry: "draft",
  nodes: [
    { id: "draft", type: "agent", next: "review", default: null, branches: [], model: null, tools: [] },
    { id: "review", type: "agent", next: "gate", default: null, branches: [], model: null, tools: [] },
    {
      id: "gate",
      type: "router",
      next: null,
      default: "revise",
      branches: [{ to: null, label: "approved" }],
      model: null,
      tools: [],
    },
    { id: "revise", type: "agent", next: "review", default: null, branches: [], model: null, tools: [] },
  ],
}

test("a board with no handoffs is one column, not a failure to lay out", () => {
  const placed = place(["a", "b", "c"], {})

  expect(placed.map((p) => p.column)).toEqual([0, 0, 0])
  expect(placed.map((p) => p.row)).toEqual([0, 1, 2])
})

test("a task sits to the right of whatever hands to it", () => {
  const placed = place(["chores", "review", "publish"], {
    chores: ["review"],
    review: ["publish"],
  })

  expect(placed).toEqual([
    { task: "chores", column: 0, row: 0 },
    { task: "review", column: 1, row: 0 },
    { task: "publish", column: 2, row: 0 },
  ])
})

test("two tasks fed by one stack up in the same column", () => {
  const placed = place(["chores", "review", "alert"], { chores: ["review", "alert"] })

  expect(placed.slice(1)).toEqual([
    { task: "review", column: 1, row: 0 },
    { task: "alert", column: 1, row: 1 },
  ])
})

test("a task waits for its furthest sender, not its nearest", () => {
  // chores -> review -> publish, and chores -> publish as well. publish must
  // land past review, or the long arrow would point backwards on screen.
  const placed = place(["chores", "review", "publish"], {
    chores: ["review", "publish"],
    review: ["publish"],
  })

  expect(placed.find((p) => p.task === "publish")?.column).toBe(2)
})

test("a cycle is unrolled into a line, not piled into one column", () => {
  const placed = place(["fix", "review"], { fix: ["review"], review: ["fix"] })

  // Nothing in a cycle has an unmet sender, so peeling stalls at once. Left
  // in a heap the tasks all share a column, and then *every* arrow between
  // them runs backwards -- including the ones that go forwards.
  expect(placed).toEqual([
    { task: "fix", column: 0, row: 0 },
    { task: "review", column: 1, row: 0 },
  ])
})

test("a cycle of three unrolls in the order they were declared", () => {
  const placed = place(["chores", "review", "publish"], {
    chores: ["review"],
    review: ["publish"],
    publish: ["chores"],
  })

  expect(placed.map((one) => one.column)).toEqual([0, 1, 2])
})

test("a handoff naming a task that is not on the board is ignored", () => {
  const placed = place(["chores"], { chores: ["gone"] })

  expect(placed).toEqual([{ task: "chores", column: 0, row: 0 }])
})

test("a walk reads entry first and every node once, loop or not", () => {
  expect(walk(LINE)).toEqual(["draft", "review", "gate", "revise"])
})

test("a node the walk cannot reach is drawn last rather than dropped", () => {
  const stray: GraphShape = {
    ...LINE,
    nodes: [...LINE.nodes, { id: "orphan", type: "agent", next: null, default: null, branches: [], model: null, tools: [] }],
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
    nodes: [{ id: "only", type: "agent", next: null, default: null, branches: [], model: null, tools: [] }],
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


// A router with two arms: the walk reads them one after the other, but the
// graph does not run one into the other.
const FORK: GraphShape = {
  entry: "classify",
  nodes: [
    { id: "classify", type: "agent", next: "route", default: null, branches: [], model: null, tools: [] },
    {
      id: "route",
      type: "router",
      next: null,
      default: "answer",
      branches: [{ to: "bug", label: "bug" }],
      model: null,
      tools: [],
    },
    { id: "answer", type: "agent", next: null, default: null, branches: [], model: null, tools: [] },
    { id: "bug", type: "agent", next: null, default: null, branches: [], model: null, tools: [] },
  ],
}

test("every node of a straight line is arrived at, bar the one it starts on", () => {
  expect(arrivals(LINE)).toEqual(["review", "gate", "revise"])
})

test("every arm of a router is arrived at, not just the first", () => {
  // The whole reason the connector hangs off the node being arrived at. On
  // the router it could be drawn to one arm only, and the other would sit
  // there looking like something nothing reaches.
  expect(arrivals(FORK)).toEqual(["route", "answer", "bug"])
})

test("a loop back draws no arrow into a node already passed", () => {
  // `revise` points at `review`, which sits to its left. An arrow there
  // would run backwards through three nodes that have nothing to do with it.
  expect(arrivals(LINE)).not.toContain("draft")
})


test("a straight line is one node per column, all on one row", () => {
  expect(depths(LINE)).toEqual([
    { id: "draft", column: 0, row: 0 },
    { id: "review", column: 1, row: 0 },
    { id: "gate", column: 2, row: 0 },
    { id: "revise", column: 3, row: 0 },
  ])
})

test("a router's arms share a column and stack under one another", () => {
  // The one thing a wrapped row of pills could never say: these are
  // alternatives at the same step, not four steps in a row.
  expect(depths(FORK)).toEqual([
    { id: "classify", column: 0, row: 0 },
    { id: "route", column: 1, row: 0 },
    { id: "answer", column: 2, row: 0 },
    { id: "bug", column: 2, row: 1 },
  ])
})

test("a loop back does not push its target into a further column", () => {
  // `revise` points at `review`, which is already placed. Counting that as
  // another step would march a cycle off the right of the border forever.
  const looping: GraphShape = {
    entry: "draft",
    nodes: [
      { id: "draft", type: "agent", next: "revise", default: null, branches: [], model: null, tools: [] },
      { id: "revise", type: "agent", next: "draft", default: null, branches: [], model: null, tools: [] },
    ],
  }
  expect(depths(looping).map((cell) => cell.column)).toEqual([0, 1])
})


test("a handoff forward is not a loop; one to an earlier column is", () => {
  const chores = { task: "chores", column: 0, row: 0 }
  const review = { task: "review", column: 1, row: 0 }
  const publish = { task: "publish", column: 1, row: 1 }

  expect(loops(chores, review)).toBe(false)
  expect(loops(review, chores)).toBe(true)
  // Same column, which is where place() puts a cycle it could not peel.
  expect(loops(publish, review)).toBe(true)
})

test("a loop goes round the outside and comes up underneath its target", () => {
  const publish = { task: "publish", column: 2, row: 0 }
  const chores = { task: "chores", column: 0, row: 0 }
  const back = backWire(publish, chores, 0)

  // Out of the sender's right edge, as any arrow leaves.
  expect(back.x1).toBe(corner(publish).x + BOX.width)
  // Round past the right-hand-most border, so the upright leg crosses nothing.
  expect(back.turn).toBeGreaterThan(corner(publish).x + BOX.width)
  // Along below every box, not straight back at header height -- which is the
  // height every box and every word is drawn at.
  expect(back.under).toBeGreaterThan(corner(publish).y + BOX.height)
  // And up into the underside, which no arrow going forwards ever does.
  expect(back.x2).toBe(corner(chores).x + BOX.width / 2)
  expect(back.y2).toBe(corner(chores).y + BOX.height)
})

test("the return leg clears the bottom row, whichever row that is", () => {
  const from = { task: "publish", column: 1, row: 0 }
  const to = { task: "chores", column: 0, row: 0 }

  expect(backWire(from, to, 2).under).toBeGreaterThan(
    corner({ task: "x", column: 0, row: 2 }).y + BOX.height,
  )
})


test("measured rows override the pitch, because a border is as tall as it is", () => {
  // BOX.height is an assumption, and since a border draws its graph on a grid
  // it is routinely wrong by more than the gap between rows. Left to the
  // arithmetic, a return leg is drawn straight through the box above it.
  const frame = { tops: [0, 300], bottom: 460, heights: { chores: 190, publish: 160 } }
  const publish = { task: "publish", column: 1, row: 1 }
  const chores = { task: "chores", column: 0, row: 0 }

  expect(corner(chores, frame).y).toBe(0)
  expect(corner(publish, frame).y).toBe(300)

  const back = backWire(publish, chores, 1, frame)
  expect(back.under).toBeGreaterThan(460)
  // Up into the target's own underside, not into a guess at where it ends.
  expect(back.y2).toBe(190)
})


test("a board smaller than the window is centred, not blown up", () => {
  // Magnifying four boxes to fill a wide screen would make the board shout at
  // a reader who only asked to see it.
  const view = fit({ width: 600, height: 300 }, { width: 1000, height: 700 })

  expect(view.zoom).toBe(1)
  expect(view.x).toBe(200)
  expect(view.y).toBe(200)
})

test("a board wider than the window is scaled to fit inside the margin", () => {
  // 1000 wide less 24 each side leaves 952, and 952 / 1904 is a half.
  const view = fit({ width: 1904, height: 100 }, { width: 1000, height: 700 })

  expect(view.zoom).toBe(0.5)
  expect(view.x).toBe(24)
})

test("height constrains the fit when it is the tighter of the two", () => {
  const view = fit({ width: 100, height: 1304 }, { width: 1000, height: 700 })

  expect(view.zoom).toBe(0.5)
  expect(view.y).toBe(24)
})

test("an empty board does not divide by zero", () => {
  // A board with nothing on it has no size, and a NaN transform blanks the
  // page rather than drawing nothing, which is much harder to diagnose.
  const view = fit({ width: 0, height: 0 }, { width: 1000, height: 700 })

  expect(Number.isFinite(view.x) && Number.isFinite(view.y)).toBe(true)
  expect(view.zoom).toBe(1)
})


test("dragging moves the board by exactly what the pointer moved", () => {
  // In screen pixels, not board ones: a drag that feels like an inch has to
  // move an inch whatever the zoom, or the board slides out from under the
  // hand that is holding it.
  const moved = pan({ x: 100, y: 50, zoom: 0.5 }, 30, -20)

  expect(moved).toEqual({ x: 130, y: 30, zoom: 0.5 })
})

test("zooming holds still whatever is under the pointer", () => {
  // The whole trick of a usable zoom. Scaling about the corner instead throws
  // the thing the reader was looking at off the screen.
  const before = { x: 0, y: 0, zoom: 1 }
  const at = { x: 400, y: 300 }
  const after = zoom(before, 2, at)

  expect(after.zoom).toBe(2)
  // The board point under the pointer was (400, 300); it must still be there.
  const board = (v: typeof before, s: typeof at) => ({
    x: (s.x - v.x) / v.zoom,
    y: (s.y - v.y) / v.zoom,
  })
  expect(board(after, at)).toEqual(board(before, at))
})

test("zoom stops short of vanishing and of filling the screen with one box", () => {
  const view = { x: 0, y: 0, zoom: 1 }

  expect(zoom(view, 100, { x: 0, y: 0 }).zoom).toBe(4)
  expect(zoom(view, 0.0001, { x: 0, y: 0 }).zoom).toBe(0.1)
})


test("the minimap shrinks the board to fit its own corner", () => {
  const map = minimap({ width: 3000, height: 600 }, { width: 200, height: 140 })

  // Widest side decides, so nothing is squashed out of proportion.
  expect(map.zoom).toBeCloseTo(200 / 3000)
  expect(map.width).toBeCloseTo(200)
  expect(map.height).toBeCloseTo(40)
})

test("the minimap draws where the window is looking", () => {
  // The board is at half scale with its top-left at the viewport's corner, so
  // the window covers the left half of a 2000-wide board.
  const seen = looking(
    { x: 0, y: 0, zoom: 0.5 },
    { width: 500, height: 250 },
    { zoom: 0.1 },
  )

  expect(seen).toEqual({ x: 0, y: 0, width: 100, height: 50 })
})

test("a window looking past the board's edge is clipped, not drawn outside it", () => {
  // Panned right, so part of what the window covers is off the board. Drawn
  // unclipped the rectangle leaves the minimap, which reads as a bug.
  const seen = looking(
    { x: -400, y: 0, zoom: 1 },
    { width: 500, height: 100 },
    { zoom: 0.1, board: { width: 600, height: 100 } },
  )

  expect(seen.x).toBeCloseTo(40)
  expect(seen.width).toBeCloseTo(20)
})


test("clicking the minimap puts that part of the board in the middle", () => {
  // A minimap you can only read is half a minimap. Clicking (60, 20) on a map
  // drawn at a tenth means board (600, 200), and that has to land in the
  // middle of a 800x400 window.
  const view = centreOn({ x: 0, y: 0, zoom: 0.5 }, { x: 600, y: 200 }, { width: 800, height: 400 })

  expect(view.zoom).toBe(0.5)
  expect(view.x).toBe(400 - 300)
  expect(view.y).toBe(200 - 100)
})
