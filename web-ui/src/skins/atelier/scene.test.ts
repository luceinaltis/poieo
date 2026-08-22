import { expect, test } from "vitest"

import {
  FOOTPRINT,
  HAMMER,
  ZOOM,
  benchLayout,
  clampZoom,
  hammerAngle,
  sparking,
  bounds,
  columnsFor,
  fit,
  fromIso,
  bubbleVisible,
  figurePose,
  lampLit,
  place,
  shelfCount,
  toIso,
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

test("the room shrinks to fit a narrow screen", () => {
  const box = { width: 830, height: 440 }

  const onPhone = fit(box, { width: 390, height: 700 })
  expect(onPhone).toBeLessThan(1)
  expect(box.width * onPhone).toBeLessThanOrEqual(391)

  // A monitor with room to spare: one bench must not be blown up to fill it.
  expect(fit(box, { width: 2400, height: 1200 })).toBe(1)
})

test("a phone gets a single column, a monitor gets several", () => {
  // Three across lays benches down the projection's diagonal, which on a tall
  // narrow screen puts two of them off-stage.
  expect(columnsFor(390)).toBe(1)
  expect(columnsFor(1400)).toBeGreaterThan(1)
})

test("a single column stacks straight down the screen", () => {
  const spots = benchLayout(3, 1).map((spot) => toIso(spot.x, spot.y))

  expect(spots[0].x).toBeCloseTo(spots[1].x)
  expect(spots[1].x).toBeCloseTo(spots[2].x)
  expect(spots[1].y).toBeGreaterThan(spots[0].y)
})

test("the arrangement fits a phone without shrinking", () => {
  const spots = benchLayout(3, columnsFor(390))
  const box = bounds(spots)

  // Nothing off the edge, and nothing squinted at: one column of three fits.
  expect(box.width).toBeLessThanOrEqual(390)
  expect(fit(box, { width: 390, height: 700 })).toBe(1)
})

test("bounds covers the drawn bench, not just its anchor", () => {
  // Centring on bare anchors pushed the room half a bench off the left edge.
  const box = bounds([{ x: 0, y: 0 }])
  expect(box.x).toBe(-FOOTPRINT.width / 2)
  expect(box.width).toBe(FOOTPRINT.width)
})

test("the room never shrinks to nothing", () => {
  // Scrolling a small room beats squinting at an unreadable one.
  expect(fit({ width: 9000, height: 9000 }, { width: 320, height: 480 })).toBe(0.35)
})

test("an empty room needs no scaling", () => {
  expect(fit({ width: 0, height: 0 }, { width: 390, height: 700 })).toBe(1)
})

test("the hammer lifts slowly and falls fast", () => {
  // An even swing reads as waving. A smith's arm spends most of the cycle on
  // the way up.
  expect(hammerAngle(0)).toBeCloseTo(HAMMER.struck)
  expect(hammerAngle(630)).toBeCloseTo(HAMMER.raised) // 70% of the way through
  expect(hammerAngle(899)).toBeGreaterThan(HAMMER.raised)

  const mid = hammerAngle(315)
  expect(mid).toBeLessThan(HAMMER.struck)
  expect(mid).toBeGreaterThan(HAMMER.raised)
})

test("the swing repeats and never leaves its arc", () => {
  for (let t = 0; t < 3000; t += 37) {
    expect(hammerAngle(t)).toBeGreaterThanOrEqual(HAMMER.raised)
    expect(hammerAngle(t)).toBeLessThanOrEqual(HAMMER.struck)
  }
  expect(hammerAngle(120)).toBeCloseTo(hammerAngle(120 + 900))
})

test("sparks fly on the strike, and only while working", () => {
  const busy = worker({ status: "running" })
  const idle = worker({ status: "waiting" })

  expect(sparking(busy, 880)).toBe(true) // just before the blow lands
  expect(sparking(busy, 300)).toBe(false) // mid-lift
  expect(sparking(idle, 880)).toBe(false) // nobody at the anvil
})

test("zoom is bounded on both sides", () => {
  expect(clampZoom(99)).toBe(ZOOM.max)
  expect(clampZoom(0.001)).toBe(ZOOM.min)
  expect(clampZoom(1.4)).toBe(1.4)
})
