import { describe, expect, it } from "vitest"
import { likeness, threaded } from "./cabin"

describe("threaded", () => {
  it("leaves a single piece's indices where they are", () => {
    const into: number[] = []
    threaded(into, [{ index: [0, 1, 2], vertices: 3 }])
    expect(into).toEqual([0, 1, 2])
  })

  it("shifts each piece past the vertices of the ones before it", () => {
    const into: number[] = []
    threaded(into, [
      { index: [0, 1, 2], vertices: 3 },
      { index: [0, 1, 2], vertices: 4 },
      { index: [0, 3, 1], vertices: 4 },
    ])
    expect(into).toEqual([0, 1, 2, 3, 4, 5, 7, 10, 8])
  })

  it("writes into a typed array as happily as an ordinary one", () => {
    const into = new Uint16Array(6)
    threaded(into, [
      { index: [0, 1, 2], vertices: 8 },
      { index: [0, 1, 2], vertices: 8 },
    ])
    expect(Array.from(into)).toEqual([0, 1, 2, 8, 9, 10])
  })
})

describe("likeness", () => {
  const plank = {
    type: "MeshStandardMaterial",
    roughness: 0.95,
    metalness: 0,
    transparent: false,
    opacity: 1,
    side: 0,
  }

  it("puts two shades of the same wood in one draw call", () => {
    // The whole point: colour moves to the vertices, so it stops being a
    // reason to draw a separate mesh.
    expect(likeness({ ...plank, color: "dark" })).toBe(likeness({ ...plank, color: "light" }))
  })

  it("keeps materials apart when they differ in more than colour", () => {
    expect(likeness({ ...plank, roughness: 0.4 })).not.toBe(likeness(plank))
    expect(likeness({ ...plank, transparent: true })).not.toBe(likeness(plank))
    expect(likeness({ ...plank, type: "MeshBasicMaterial" })).not.toBe(likeness(plank))
  })

  it("keeps a textured material out of a merge that assumes none", () => {
    expect(likeness({ ...plank, map: {} })).not.toBe(likeness(plank))
  })
})
