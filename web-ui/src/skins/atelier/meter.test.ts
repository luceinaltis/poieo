import { describe, expect, it } from "vitest"
import { reading } from "./meter"

const cost = { calls: 42, triangles: 160_000 }

describe("reading", () => {
  it("says the frame rate and that the clock keeps up with it", () => {
    expect(reading(60, 1000, 1000, cost)).toBe("60 fps   1.00x speed   42 draws   160k tris")
  })

  it("separates a slow clock from a slow draw", () => {
    // Half the frames but the clock still real: a scene too heavy to draw.
    expect(reading(30, 1000, 1000, cost)).toContain("30 fps   1.00x speed")
    // The bug clock.ts fixed: frames fine, everything in slow motion.
    expect(reading(30, 1000, 480, cost)).toContain("30 fps   0.48x speed")
  })

  it("says nothing rather than dividing by no time at all", () => {
    expect(reading(0, 0, 0, cost)).toBe("...")
  })
})
