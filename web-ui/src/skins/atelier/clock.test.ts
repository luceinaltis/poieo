import { describe, expect, it } from "vitest"
import { LONGEST_STEP, step } from "./clock"

describe("step", () => {
  it("is the real time between two frames", () => {
    expect(step(1016.7, 1000)).toBeCloseTo(16.7)
  })

  it("is the real time between two slow ones, not a nominal frame", () => {
    // The bug this exists for: a phone drawing at thirty frames a second used
    // to advance the workshop 16 ms per frame, so it ran at half speed.
    expect(step(1033.3, 1000)).toBeCloseTo(33.3)
  })

  it("is nothing on the first frame, which has no frame before it", () => {
    expect(step(1234.5, -1)).toBe(0)
  })

  it("is nothing when the timestamp has not moved", () => {
    expect(step(1000, 1000)).toBe(0)
    expect(step(999, 1000)).toBe(0)
  })

  it("caps a backgrounded tab's absence rather than replaying it", () => {
    expect(step(400_000, 1000)).toBe(LONGEST_STEP)
  })
})
