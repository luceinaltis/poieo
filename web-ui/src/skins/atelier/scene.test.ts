import { expect, test } from "vitest"

import {
  FOOTPRINT,
  benchLayout,
  fromIso,
  bubbleVisible,
  figurePose,
  lampLit,
  place,
  shelfCount,
  toIso,
  transitionMs,
} from "./scene"
import { NOTHING } from "../../review/rollup"
import type { Worker } from "../../state/stage"

function worker(over: Partial<Worker> = {}): Worker {
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
    tracked: true,
    ...over,
  }
}

test("the isometric projection halves the vertical axis", () => {
  // A 2:1 projection: equal steps along both floor axes must not land on the
  // same screen point, or benches behind one another become invisible.
  expect(toIso(0, 0)).toEqual({ x: 0, y: 0 })
  expect(toIso(1, 0)).not.toEqual(toIso(0, 1))
  expect(toIso(2, 2).y).toBeGreaterThan(toIso(1, 1).y)
})

test("a dragged bench round-trips through the projection", () => {
  // What is stored is the floor position, so it has to survive the trip back.
  for (const spot of [{ x: 0, y: 0 }, { x: 220, y: 150 }, { x: -80, y: 33 }]) {
    const screen = toIso(spot.x, spot.y)
    const back = fromIso(screen.x, screen.y)
    expect(back.x).toBeCloseTo(spot.x)
    expect(back.y).toBeCloseTo(spot.y)
  }
})

test("benchLayout keeps benches apart on screen, not just on the floor", () => {
  // The first version of this measured floor coordinates, which the
  // projection then halves and quarters -- so it passed while the benches
  // overlapped by more than half their width.
  const spots = benchLayout(7).map((spot) => toIso(spot.x, spot.y))

  expect(spots).toHaveLength(7)
  for (let i = 0; i < spots.length; i += 1) {
    for (let j = i + 1; j < spots.length; j += 1) {
      const dx = Math.abs(spots[i].x - spots[j].x)
      const dy = Math.abs(spots[i].y - spots[j].y)
      expect(dx >= FOOTPRINT.width || dy >= FOOTPRINT.height).toBe(true)
    }
  }
})

test("a bench the reader moved stays where they put it", () => {
  const auto = benchLayout(3)
  const placed = place(["a", "b", "c"], { b: { x: 999, y: 42 } })

  expect(placed.a).toEqual(auto[0])
  expect(placed.b).toEqual({ x: 999, y: 42 })
  // moving one must not shuffle the others
  expect(placed.c).toEqual(auto[2])
})

test("a saved position for a flow that is gone is ignored", () => {
  const placed = place(["a"], { ghost: { x: 5, y: 5 } })
  expect(Object.keys(placed)).toEqual(["a"])
})

test("figurePose maps the three states to three poses", () => {
  const poses = new Set([
    figurePose(worker({ status: "waiting" })),
    figurePose(worker({ status: "running" })),
    figurePose(worker({ status: "error" })),
  ])
  expect(poses.size).toBe(3)
})

test("the lamp is lit while the bench is in use", () => {
  expect(lampLit(worker({ status: "running" }))).toBe(true)
  expect(lampLit(worker({ status: "waiting" }))).toBe(false)
})

test("the bubble appears only when there is a thought to show", () => {
  expect(bubbleVisible(worker({ lastThinking: "" }))).toBe(false)
  expect(bubbleVisible(worker({ lastThinking: "hm" }))).toBe(true)
})

test("a flow with no private copy shelves nothing", () => {
  // It produces no piece to put anywhere. Counting its runs as finished work
  // fills a shelf with things that do not exist.
  const busy = worker({
    tracked: false,
    recent: { ...NOTHING, works: 40, succeeded: 40 },
  })
  expect(shelfCount(busy)).toBe(0)
})

test("the shelf fills with finished work, not attempts", () => {
  expect(shelfCount(worker())).toBe(0)
  expect(shelfCount(worker({ recent: { ...NOTHING, works: 4, succeeded: 3 } }))).toBe(3)
  // a failed night leaves the shelf empty
  expect(shelfCount(worker({ recent: { ...NOTHING, works: 2, failed: 2 } }))).toBe(0)
})

test("reduced motion means no tween at all", () => {
  expect(transitionMs(false)).toBeGreaterThan(0)
  expect(transitionMs(true)).toBe(0)
})
