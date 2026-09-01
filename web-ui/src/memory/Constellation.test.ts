import { expect, test } from "vitest"

import {
  edgeHasArrow,
  edgeUsesCurve,
  fitConstellationScale,
  NODE_LABEL_FONT_PX,
  perspectiveForDepth,
} from "./Constellation"

test("directional memory relationships get arrowheads", () => {
  expect(edgeHasArrow("mentions")).toBe(true)
  expect(edgeHasArrow("depends_on")).toBe(true)
  expect(edgeHasArrow("supersedes")).toBe(true)
  expect(edgeHasArrow("contradicts")).toBe(false)
})

test("large constellations trade decorative curves for responsive orbiting", () => {
  expect(edgeUsesCurve(47)).toBe(true)
  expect(edgeUsesCurve(12_000)).toBe(false)
})

test("depth changes the apparent scale enough to read as three-dimensional", () => {
  expect(perspectiveForDepth(0)).toBe(1)
  expect(perspectiveForDepth(1)).toBeGreaterThan(1.3)
  expect(perspectiveForDepth(-1)).toBeLessThan(0.8)
})

test("canvas labels stay readable beside the compact interface", () => {
  expect(NODE_LABEL_FONT_PX).toBeGreaterThanOrEqual(13)
})

test("the initial view fits projected outer memories inside the canvas", () => {
  const width = 960
  const height = 720
  const points = [{ x: -1.8, y: -1.4 }, { x: 1.5, y: 1.7 }]
  const scale = fitConstellationScale(width, height, points)

  expect(((1.5 - -1.8) / 2) * scale).toBeLessThanOrEqual(width * 0.44)
  expect(((1.7 - -1.4) / 2) * scale).toBeLessThanOrEqual(height * 0.42)
})
