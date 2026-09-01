import { expect, test } from "vitest"

import { edgeHasArrow } from "./Constellation"

test("directional memory relationships get arrowheads", () => {
  expect(edgeHasArrow("mentions")).toBe(true)
  expect(edgeHasArrow("depends_on")).toBe(true)
  expect(edgeHasArrow("supersedes")).toBe(true)
  expect(edgeHasArrow("contradicts")).toBe(false)
})
