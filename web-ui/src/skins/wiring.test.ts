import { expect, test } from "vitest"

import {
  BOX, ZOOM, backWire, centreOn, corner, exits, fit, looking, loops, minimap,
  place, walk, wire,
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

test("a board with no handoffs is a grid, because the axis is carrying nothing", () => {
  // It was one column, on the argument that independent work must not read as
  // a failure to lay anything out. The column was what read that way: the
  // left-to-right axis means depth only while something points somewhere, and
  // with nothing pointing it is free to be used for reading.
  const placed = place(["a", "b", "c"], {}, 4)

  expect(placed.map((p) => p.column)).toEqual([0, 1, 2])
  expect(placed.map((p) => p.row)).toEqual([0, 0, 0])
})

test("a grid wraps rather than running off the side of the board", () => {
  const placed = place(["a", "b", "c", "d", "e"], {}, 2)

  expect(placed.map((p) => [p.column, p.row])).toEqual([
    [0, 0],
    [1, 0],
    [0, 1],
    [1, 1],
    [0, 2],
  ])
})

test("one arrow anywhere gives the axis its meaning back", () => {
  const placed = place(["a", "b", "c"], { a: ["b"] })

  // `c` hands to nobody, but the board now reads left to right, so it keeps
  // its place in the first column rather than being packed beside `b`.
  expect(placed.map((p) => p.column)).toEqual([0, 1, 0])
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


/* Where a step sits inside a border, and which of them a line arrives at, are
   `dagre`'s now -- `basic/steps.test.ts` asserts what the picture *means*
   there, and the coordinates are not restated because pinning them would make
   dagre's next release a failing suite rather than a layout that moved by two
   pixels. What those tests said, and what `steps.test.ts` still says in its
   own words: a router's arms are alternatives at one step rather than four
   steps in a row, and a loop back does not march off the edge of the border. */

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


/* Dragging and scaling by hand are `d3-zoom`'s now, and how a gesture moves a
   view is its business to get right rather than this suite's to restate. What
   stays here is what remains poieo's: the bounds those gestures are held to,
   and the fit and the minimap below, which are arithmetic about this board. */

test("zoom stops short of vanishing and of filling the screen with one box", () => {
  // Handed to d3 as its scale extent. The ceiling stops a board becoming one
  // box and a lot of felt; the floor is deliberately below what a fit may use,
  // because seeing the whole shape is worth more than legible type and there
  // is no other way to get it.
  expect(ZOOM).toEqual({ min: 0.1, max: 4 })
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
