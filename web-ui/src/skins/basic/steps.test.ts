/**
 * Laying a task's own steps out as a graph.
 *
 * What is asserted here is what poieo means, not what dagre computes: that
 * every step is placed, that every edge in the graph is drawn, that a branch
 * carries its word, and that a cycle does not send the layout off the end of
 * the world. Exact coordinates are dagre's business and are not restated --
 * pinning them here would make its next release a failing suite rather than a
 * layout that moved by two pixels.
 */

import { expect, test } from "vitest"

import { layOutSteps } from "./steps"
import type { GraphShape } from "../../types"

const step = (id: string, over: Partial<GraphShape["nodes"][number]> = {}) => ({
  id,
  type: "agent",
  next: null,
  default: null,
  branches: [],
  model: null,
  tools: [],
  ...over,
})

/** classify -> route, and route branches three ways. */
const TRIAGE: GraphShape = {
  entry: "classify",
  nodes: [
    step("classify", { next: "route" }),
    step("route", {
      type: "router",
      default: "draft_answer",
      branches: [
        { to: "draft_bug", label: "bug" },
        { to: "draft_feature", label: "feature" },
      ],
    }),
    step("draft_bug"),
    step("draft_feature"),
    step("draft_answer"),
  ],
}

test("every step is placed, and the box is big enough to hold them", () => {
  const laid = layOutSteps(TRIAGE, () => ({ width: 80, height: 24 }))

  expect(laid.steps.map((s) => s.id).sort()).toEqual(
    ["classify", "draft_answer", "draft_bug", "draft_feature", "route"].sort(),
  )
  for (const one of laid.steps) {
    expect(one.x).toBeGreaterThanOrEqual(0)
    expect(one.y).toBeGreaterThanOrEqual(0)
    expect(one.x).toBeLessThanOrEqual(laid.width)
    expect(one.y).toBeLessThanOrEqual(laid.height)
  }
})

test("every way out of a step is an edge, default included", () => {
  const laid = layOutSteps(TRIAGE, () => ({ width: 80, height: 24 }))
  const drawn = laid.edges.map((e) => `${e.from}->${e.to}`).sort()

  // The default arm is a way the run can go, so it is a line like any other.
  // Left out, a router would appear to have two arms where it has three.
  expect(drawn).toEqual(
    ["classify->route", "route->draft_answer", "route->draft_bug", "route->draft_feature"].sort(),
  )
  for (const edge of laid.edges) expect(edge.points.length).toBeGreaterThan(1)
})

test("a branch carries the word that chooses it", () => {
  const laid = layOutSteps(TRIAGE, () => ({ width: 80, height: 24 }))
  const words = Object.fromEntries(laid.edges.map((e) => [e.to, e.label]))

  expect(words.draft_bug).toBe("bug")
  expect(words.draft_feature).toBe("feature")
  // `default` is the arm taken when no condition matched, and saying so is the
  // only way a reader can tell it from the ones that were chosen.
  expect(words.draft_answer).toBe("default")
  // A step with one way on has nothing to choose, so nothing to say.
  expect(words.route).toBe("")
})

test("a step that goes nowhere is drawn, and says the run can end there", () => {
  const laid = layOutSteps(TRIAGE, () => ({ width: 80, height: 24 }))
  const ends = laid.steps.filter((s) => s.ends).map((s) => s.id)

  expect(ends.sort()).toEqual(["draft_answer", "draft_bug", "draft_feature"])
})

test("a cycle is laid out rather than run off the end of the world", () => {
  // `examples/tasks/draft-review.graph.yaml` loops until a critic approves, so
  // this is an ordinary graph here and not an edge case.
  const loop: GraphShape = {
    entry: "draft",
    nodes: [
      step("draft", { next: "review" }),
      step("review", { next: "gate" }),
      step("gate", { type: "router", default: "revise", branches: [{ to: null, label: "approved" }] }),
      step("revise", { next: "review" }),
    ],
  }

  const laid = layOutSteps(loop, () => ({ width: 80, height: 24 }))

  // The four steps, and not the terminal `gate`'s approved arm lands on.
  expect(laid.steps.filter((one) => !one.stop)).toHaveLength(4)
  expect(laid.width).toBeGreaterThan(0)
  expect(laid.height).toBeGreaterThan(0)
  // The way back is a line like the others; without it the loop reads as a
  // chain that stops.
  expect(laid.edges.some((e) => e.from === "revise" && e.to === "review")).toBe(true)
})

test("a branch that ends the run is drawn, because ending is a way to go", () => {
  const laid = layOutSteps(
    {
      entry: "gate",
      nodes: [
        step("gate", { type: "router", default: "work", branches: [{ to: null, label: "approved" }] }),
        step("work"),
      ],
    },
    () => ({ width: 80, height: 24 }),
  )

  const stop = laid.edges.find((e) => e.to === null)
  expect(stop?.label).toBe("approved")
  expect(stop?.points.length).toBeGreaterThan(1)
  // It needs somewhere to land, or there is no line -- a small terminal of its
  // own, one per arm, so two different ways of ending do not collapse into one.
  expect(laid.steps.some((s) => s.stop)).toBe(true)
})

test("one step is a graph of one, not an empty box", () => {
  const laid = layOutSteps(
    { entry: "work", nodes: [step("work", { tools: ["files"] })] },
    () => ({ width: 80, height: 24 }),
  )

  expect(laid.steps).toHaveLength(1)
  expect(laid.edges).toHaveLength(0)
  expect(laid.width).toBeGreaterThan(0)
})
