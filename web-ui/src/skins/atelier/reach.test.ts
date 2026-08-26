import { describe, expect, it } from "vitest"
import { flexion, sideways, stretcher } from "./reach"

/** Just enough of a Vector3 for the joints this moves. */
function at(x: number, y: number, z: number) {
  const self = {
    x,
    y,
    z,
    clone: () => at(self.x, self.y, self.z),
    copy(from: any) {
      self.x = from.x
      self.y = from.y
      self.z = from.z
      return self
    },
    multiplyScalar(by: number) {
      self.x *= by
      self.y *= by
      self.z *= by
      return self
    },
  }
  return self
}

describe("stretcher", () => {
  it("sets a joint out along its own bone", () => {
    const elbow = { position: at(0, 20, 0) }
    stretcher([elbow], 1.5)()
    expect(elbow.position.y).toBeCloseTo(30)
  })

  it("leaves a joint alone at a factor of one", () => {
    const wrist = { position: at(1, 20, -2) }
    stretcher([wrist], 1)()
    expect([wrist.position.x, wrist.position.y, wrist.position.z]).toEqual([1, 20, -2])
  })

  it("does not compound when the mixer skips a frame", () => {
    // The mixer only rewrites a track whose value changed, so a still pose
    // leaves the bone where the last call put it. Setting from the rest
    // position rather than multiplying in place is what keeps this stable --
    // multiplying would reach 1.33^40, and the arm would leave the room.
    const elbow = { position: at(0, 20, 0) }
    const stretch = stretcher([elbow], 1.33)
    for (let frame = 0; frame < 40; frame += 1) stretch()
    expect(elbow.position.y).toBeCloseTo(26.6)
  })

  it("moves every joint it was given", () => {
    const joints = [{ position: at(0, 20, 0) }, { position: at(0, 18, 0) }]
    stretcher(joints, 2)()
    expect(joints.map((j) => j.position.y)).toEqual([40, 36])
  })
})

describe("flexion", () => {
  const straight = { x: 0, y: -1, z: 0 }

  it("is nothing when the arm is straight", () => {
    expect(flexion(straight, { x: 0, y: -2, z: 0 })).toBeCloseTo(0)
  })

  it("is a right angle when the forearm turns square", () => {
    expect(flexion(straight, { x: 0, y: 0, z: 1 })).toBeCloseTo(Math.PI / 2)
  })

  it("does not care how long either bone is", () => {
    const near = flexion({ x: 0, y: -1, z: 0 }, { x: 0, y: -1, z: 1 })
    const far = flexion({ x: 0, y: -9, z: 0 }, { x: 0, y: -3, z: 3 })
    expect(far).toBeCloseTo(near)
  })
})

describe("sideways", () => {
  const up = { x: 0, y: 1, z: 0 }
  const outward = { x: 1, y: 0, z: 0 }

  it("is nothing for an arm hanging straight down", () => {
    expect(sideways({ x: 0, y: -1, z: 0 }, outward, up)).toBeCloseTo(0)
  })

  it("is positive for an arm held clear of the body", () => {
    expect(sideways({ x: 1, y: -1, z: 0 }, outward, up)).toBeCloseTo(Math.PI / 4)
  })

  it("is negative for an arm pressed into it", () => {
    expect(sideways({ x: -1, y: -1, z: 0 }, outward, up)).toBeCloseTo(-Math.PI / 4)
  })

  it("ignores what the arm does front to back", () => {
    // The clip swings the arm forward all through the idle; only the tuck
    // against the ribs is this correction's business.
    const flat = sideways({ x: 1, y: -1, z: 0 }, outward, up)
    const forward = sideways({ x: 1, y: -1, z: 4 }, outward, up)
    expect(forward).toBeCloseTo(flat)
  })
})
